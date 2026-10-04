import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
import respx
from fakeredis import FakeAsyncRedis

from app.config import Settings
from app.core import limits, tasks
from tests.conftest import ADMIN_HEADERS

pytestmark = pytest.mark.respx(assert_all_called=False)

MESSAGES = [{"role": "user", "content": "hi"}]


def completion(total: int) -> dict:
    return {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": total},
    }


def bearer(key: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {key['key']}"}


async def chat(client: httpx.AsyncClient, key: dict, **extra) -> httpx.Response:
    return await client.post(
        "/v1/chat/completions", json={"model": "fast", "messages": MESSAGES, **extra}, headers=bearer(key)
    )


async def test_rpm_limit_isolated_per_key(
    client: httpx.AsyncClient, create_key, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(f"{settings.gemini_base_url}/chat/completions").mock(
        return_value=httpx.Response(200, json=completion(2))
    )
    limited, other = await create_key(rpm=3), await create_key(rpm=3)

    statuses = [(await chat(client, limited)).status_code for _ in range(5)]
    blocked = await chat(client, limited)

    assert statuses == [200, 200, 200, 429, 429]
    assert blocked.json()["error"]["type"] == "rate_limit"
    assert 1 <= int(blocked.headers["retry-after"]) <= 60
    assert blocked.headers["x-ratelimit-limit-requests"] == "3"
    assert blocked.headers["x-ratelimit-remaining-requests"] == "0"  # clamped, not negative
    assert (await chat(client, other)).status_code == 200  # second key unaffected


async def test_rate_limit_headers(
    client: httpx.AsyncClient, create_key, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(f"{settings.gemini_base_url}/chat/completions").mock(
        return_value=httpx.Response(200, json=completion(7))
    )
    key = await create_key(rpm=10, daily_token_quota=100)

    resp = await chat(client, key)

    assert resp.headers["x-ratelimit-limit-requests"] == "10"
    assert resp.headers["x-ratelimit-remaining-requests"] == "9"
    assert resp.headers["x-ratelimit-remaining-tokens"] == "100"  # usage is counted after the response


async def test_daily_quota_uses_total_tokens(
    client: httpx.AsyncClient, create_key, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(f"{settings.gemini_base_url}/chat/completions").mock(
        return_value=httpx.Response(200, json=completion(60))
    )
    key = await create_key(daily_token_quota=100)

    assert (await chat(client, key)).status_code == 200  # 60 used
    assert (await chat(client, key)).status_code == 200  # 120 used, over quota from now on
    blocked = await chat(client, key)

    assert blocked.status_code == 429
    assert blocked.json()["error"]["type"] == "quota_exceeded"
    assert blocked.headers["x-ratelimit-limit-tokens"] == "100"
    assert blocked.headers["x-ratelimit-remaining-tokens"] == "0"
    listed = (await client.get("/admin/keys", headers=ADMIN_HEADERS)).json()
    assert listed[0]["tokens_today"] == 120


async def test_stream_usage_is_recorded(
    client: httpx.AsyncClient, create_key, redis: FakeAsyncRedis, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
        # usage split across two network chunks
        yield b'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_'
        yield b'tokens":5,"total_tokens":9}}\n\ndata: [DONE]\n\n'

    respx_mock.post(f"{settings.gemini_base_url}/chat/completions").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body())
    )
    key = await create_key()

    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": "fast", "messages": MESSAGES, "stream": True},
        headers=bearer(key),
    ) as resp:
        _ = [chunk async for chunk in resp.aiter_bytes()]

    await tasks.drain()
    used = await redis.get(limits.token_key(uuid.UUID(key["id"]), datetime.now(UTC)))
    assert used == "9"


async def test_redis_down_returns_503(make_client, create_key) -> None:
    key = await create_key()
    async with make_client(redis_up=False) as down:
        resp = await down.get("/v1/models", headers=bearer(key))
    assert resp.status_code == 503
    assert resp.json()["error"]["type"] == "service_unavailable"


def test_seconds_to_midnight() -> None:
    now = datetime(2026, 1, 1, 23, 59, 30, tzinfo=UTC)
    assert limits._seconds_to_midnight(now) == 30


async def test_record_tokens_ignores_zero(redis: FakeAsyncRedis) -> None:
    await limits.record_tokens(redis, uuid.uuid4(), 0)
    assert await redis.dbsize() == 0
