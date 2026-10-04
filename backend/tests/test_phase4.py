import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import func, select

from app.config import Settings
from app.db.analytics import percentile as _percentile
from app.db.models import RequestLog
from app.logging_queue import LogEvent, LogQueue
from tests.conftest import ADMIN_HEADERS

pytestmark = pytest.mark.respx(assert_all_called=False)

MESSAGES = [{"role": "user", "content": "hi"}]


def completion(total: int = 10) -> dict:
    return {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": total},
    }


def event(**overrides) -> LogEvent:
    base = dict(
        ts=datetime.now(UTC),
        key_id=None,
        alias="fast",
        model_used="m",
        in_tokens=1,
        out_tokens=1,
        latency_ms=10,
        status=200,
        cache_hit=False,
        fallback_used=False,
    )
    return LogEvent(**{**base, **overrides})


async def row_count(app: FastAPI) -> int:
    async with app.state.sessionmaker() as session:
        return await session.scalar(select(func.count()).select_from(RequestLog))


@pytest.fixture
def gemini(settings: Settings, respx_mock: respx.MockRouter) -> respx.Route:
    return respx_mock.post(f"{settings.gemini_base_url}/chat/completions")


async def test_request_path_only_buffers(client, auth, app: FastAPI, gemini) -> None:
    gemini.mock(return_value=httpx.Response(200, json=completion()))

    await client.post("/v1/chat/completions", json={"model": "fast", "messages": MESSAGES}, headers=auth)

    assert len(app.state.log_queue) == 1
    assert await row_count(app) == 0  # nothing written until the flusher runs
    assert await app.state.log_queue.flush() == 1
    assert await row_count(app) == 1


async def test_every_outcome_is_logged(client, auth, app: FastAPI, gemini, settings: Settings) -> None:
    async def sse() -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
        yield b'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":4,"total_tokens":9}}\n\n'

    gemini.mock(return_value=httpx.Response(200, json=completion(total=12)))
    deterministic = {"model": "fast", "messages": MESSAGES, "temperature": 0}
    for _ in range(3):  # first sighting not stored, second stored, third served from cache
        await client.post("/v1/chat/completions", json=deterministic, headers=auth)
    await client.post("/v1/chat/completions", json={"model": "nope", "messages": MESSAGES}, headers=auth)
    gemini.mock(return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse()))
    async with client.stream(
        "POST", "/v1/chat/completions", json={"model": "fast", "messages": MESSAGES, "stream": True}, headers=auth
    ) as resp:
        _ = [c async for c in resp.aiter_bytes()]
    await app.state.log_queue.flush()

    page = (await client.get("/admin/logs", headers=ADMIN_HEADERS)).json()
    stream_log, unknown_alias, cache_hit, miss, rejected = page["items"]  # newest first
    assert (rejected["cache_status"], miss["cache_status"], cache_hit["cache_status"]) == (
        "admission_rejected",
        "miss",
        "hit",
    )
    assert stream_log["cache_status"] == "ineligible" and stream_log["ttft_ms"] is not None
    assert (miss["status"], miss["cache_hit"], miss["in_tokens"], miss["out_tokens"]) == (200, False, 4, 8)
    assert miss["model_used"] == settings.gemini_fast_model and miss["key_prefix"].startswith("tg_live_")
    assert (cache_hit["cache_hit"], cache_hit["in_tokens"] + cache_hit["out_tokens"]) == (True, 0)
    assert (unknown_alias["status"], unknown_alias["model_used"]) == (404, None)
    assert (stream_log["status"], stream_log["in_tokens"], stream_log["out_tokens"]) == (200, 3, 6)


async def test_stats_aggregate(client, app: FastAPI, create_key) -> None:
    key = await create_key(name="team-a")
    key_id = uuid.UUID(key["id"])
    queue: LogQueue = app.state.log_queue
    for latency in (10, 20, 30, 40, 100):
        queue.enqueue(event(key_id=key_id, latency_ms=latency, in_tokens=5, out_tokens=5))
    queue.enqueue(event(key_id=key_id, status=503, model_used="other", in_tokens=0, out_tokens=0))
    queue.enqueue(event(key_id=key_id, cache_hit=True, in_tokens=0, out_tokens=0))
    queue.enqueue(event(key_id=key_id, fallback_used=True, in_tokens=0, out_tokens=0))
    queue.enqueue(event(ts=datetime.now(UTC) - timedelta(days=3)))  # outside the 24h window
    await queue.flush()

    stats = (await client.get("/admin/stats", headers=ADMIN_HEADERS)).json()

    assert stats["requests"] == 8
    assert (stats["errors"], stats["error_rate"]) == (1, 0.125)
    assert (stats["cache_hits"], stats["cache_hit_rate"]) == (1, 0.125)
    assert stats["fallbacks"] == 1
    assert (stats["in_tokens"], stats["out_tokens"]) == (25, 25)
    assert stats["p50_latency_ms"] == 15.0  # [10, 10, 10, 10, 20, 30, 40, 100]
    assert stats["by_key"] == [
        {"key_id": key["id"], "name": "team-a", "prefix": key["prefix"], "requests": 8, "tokens": 50, "errors": 1}
    ]
    assert {m["name"]: m["requests"] for m in stats["by_model"]} == {"m": 7, "other": 1}

    wide = (await client.get("/admin/stats?hours=168", headers=ADMIN_HEADERS)).json()
    assert wide["requests"] == 9


async def test_logs_filters_and_pagination(client, app: FastAPI, create_key) -> None:
    key = await create_key()
    queue: LogQueue = app.state.log_queue
    for i in range(5):
        queue.enqueue(event(key_id=uuid.UUID(key["id"]), alias="smart" if i % 2 else "fast", status=200 + i * 100))
    await queue.flush()

    first = (await client.get("/admin/logs?limit=2", headers=ADMIN_HEADERS)).json()
    second = (await client.get(f"/admin/logs?limit=2&before={first['next_cursor']}", headers=ADMIN_HEADERS)).json()
    last = (await client.get(f"/admin/logs?limit=2&before={second['next_cursor']}", headers=ADMIN_HEADERS)).json()

    ids = [i["id"] for page in (first, second, last) for i in page["items"]]
    assert ids == sorted(ids, reverse=True) and len(set(ids)) == 5
    assert last["next_cursor"] is None
    smart = (await client.get("/admin/logs?alias=smart", headers=ADMIN_HEADERS)).json()["items"]
    assert {i["alias"] for i in smart} == {"smart"} and len(smart) == 2
    errors = (await client.get("/admin/logs?errors_only=true", headers=ADMIN_HEADERS)).json()["items"]
    assert sorted(i["status"] for i in errors) == [400, 500, 600]
    by_status = (await client.get("/admin/logs?status=300", headers=ADMIN_HEADERS)).json()["items"]
    assert [i["status"] for i in by_status] == [300]


async def test_admin_analytics_require_token(client) -> None:
    assert (await client.get("/admin/stats")).status_code == 401
    assert (await client.get("/admin/logs")).status_code == 401


async def test_failed_flush_is_retried(app: FastAPI) -> None:
    queue = LogQueue(app.state.sessionmaker, interval=1)
    queue.enqueue(event(alias=None))  # violates NOT NULL -> insert fails
    assert await queue.flush() == 0
    assert len(queue) == 1  # kept for the next cycle


def test_buffer_cap_drops_instead_of_blocking(app: FastAPI) -> None:
    queue = LogQueue(app.state.sessionmaker, interval=1, max_buffer=2)
    for _ in range(5):
        queue.enqueue(event())
    assert len(queue) == 2


def test_percentile_matches_percentile_cont() -> None:
    assert _percentile([], 0.5) is None
    assert _percentile([10, 20, 30, 40], 0.5) == 25
    assert _percentile([10, 20, 30, 40, 100], 0.95) == pytest.approx(88.0)


async def test_aliases_endpoint(client, settings: Settings) -> None:
    aliases = {a["id"]: a for a in (await client.get("/admin/aliases", headers=ADMIN_HEADERS)).json()}
    assert aliases["smart"]["chain"] == [settings.gemini_smart_model, settings.gemini_fast_model]
    assert aliases["smart-terse"]["terse"] is True
    assert aliases["demo-failover"]["chain"][0] == "mock-500"
