"""In-process benchmark harness: the real gateway app, a simulated upstream, real or fake Redis.

The upstream is an httpx.MockTransport handler, so no network or API key is involved and runs are
reproducible. A simulated "GPU" (a FIFO semaphore with per-token latency) stands in for a model server.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
import redis.asyncio as aioredis
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.session import create_sessionmaker, init_db
from app.logging_queue import LogQueue
from app.main import create_app

ADMIN = {"Authorization": "Bearer bench-admin"}


@dataclass
class SimulatedModel:
    """Answers chat completions after prefill + per-output-token time, `slots` at a time (FIFO)."""

    slots: int = 1
    prefill_s: float = 0.0
    per_token_s: float = 0.0
    output_tokens: Callable[[str], int] = lambda prompt: 50
    content: Callable[[str], str] = lambda prompt: "ok"
    calls: int = 0
    served: list[tuple[str, float]] = field(default_factory=list)  # (prompt, finish time)
    _gpu: asyncio.Semaphore | None = None

    async def handle(self, request: httpx.Request) -> httpx.Response:
        import json

        if self._gpu is None:
            self._gpu = asyncio.Semaphore(self.slots)
        body = json.loads(request.content)
        prompt = body["messages"][-1]["content"]
        self.calls += 1
        out = self.output_tokens(prompt)
        async with self._gpu:
            await asyncio.sleep(self.prefill_s + out * self.per_token_s)
        self.served.append((prompt, time.perf_counter()))
        return httpx.Response(
            200,
            json={
                "id": "bench",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": self.content(prompt)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": max(1, len(prompt) // 4),
                    "completion_tokens": out,
                    "total_tokens": out + len(prompt) // 4,
                },
            },
        )


@asynccontextmanager
async def gateway(
    model: SimulatedModel,
    *,
    redis_url: str | None = None,
    redis_cache_url: str | None = None,
    **overrides: Any,
) -> AsyncIterator[httpx.AsyncClient]:
    """A client for the real gateway app wired to `model`. Real Redis when URLs are given."""
    settings = Settings(
        _env_file=None,
        environment="test",
        log_level="WARNING",
        upstream_provider="gemini",
        gemini_api_key="bench",
        gemini_base_url="http://model.bench/v1",
        admin_token="bench-admin",
        **overrides,
    )
    app = create_app(settings, use_lifespan=False)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    await init_db(engine)
    state_redis = (
        aioredis.from_url(redis_url, decode_responses=True) if redis_url else FakeAsyncRedis(decode_responses=True)
    )
    cache_redis = aioredis.from_url(redis_cache_url, decode_responses=True) if redis_cache_url else state_redis
    app.state.redis, app.state.redis_cache, app.state.engine = state_redis, cache_redis, engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.log_queue = LogQueue(app.state.sessionmaker, 3600, max_buffer=1)  # logging is not under test
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(model.handle), timeout=600)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway", timeout=600) as client:
            client.app = app  # type: ignore[attr-defined]
            yield client
    finally:
        await app.state.http.aclose()
        await app.state.coalescer.shutdown()
        await engine.dispose()


async def create_key(client: httpx.AsyncClient, name: str) -> dict[str, str]:
    resp = await client.post(
        "/admin/keys", json={"name": name, "rpm": 100_000, "daily_token_quota": 1_000_000_000}, headers=ADMIN
    )
    resp.raise_for_status()
    key = resp.json()
    return {"Authorization": f"Bearer {key['key']}", "x-key-id": key["id"]}


async def chat(client: httpx.AsyncClient, auth: dict[str, str], prompt: str, **body: Any) -> httpx.Response:
    payload = {"model": body.pop("model", "fast"), "messages": [{"role": "user", "content": prompt}], **body}
    return await client.post("/v1/chat/completions", json=payload, headers={"Authorization": auth["Authorization"]})


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    pos = (len(ordered) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def jain(values: list[float]) -> float:
    values = [v for v in values if v > 0]
    return sum(values) ** 2 / (len(values) * sum(v * v for v in values)) if values else float("nan")


def table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)
