"""Regression tests for issues found in the pre-merge review."""

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from redis.exceptions import ConnectionError as RedisConnectionError

from app.config import Settings, Upstream
from app.core import cache
from app.core.coalesce import Coalescer, Flight
from app.core.fallback import CircuitBreakers
from app.errors import GatewayError
from tests.conftest import ADMIN_HEADERS

pytestmark = pytest.mark.respx(assert_all_called=False)

MESSAGES = [{"role": "user", "content": "hi"}]
COMPLETION = {
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


async def test_new_request_never_joins_a_cancelling_flight() -> None:
    coalescer = Coalescer()
    started = asyncio.Event()

    async def slow(_: Flight) -> str:
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            await asyncio.sleep(0.01)  # unwinding takes a moment (closing the upstream connection)
        return "x"

    doomed, _ = coalescer.join("k", slow)
    await started.wait()
    coalescer.leave(doomed)  # the only listener disconnects -> cancellation starts
    fresh, role = coalescer.join("k", slow)  # arrives while the old task unwinds
    assert fresh is not doomed and role == "leader"
    with pytest.raises(GatewayError) as err:  # a gateway error, never a bare CancelledError
        await doomed.wait_result()
    assert err.value.type == "upstream_cancelled"
    coalescer.leave(fresh)


async def test_mid_stream_failure_is_reported_and_logged(
    client, auth, app: FastAPI, settings: Settings, respx_mock
) -> None:
    async def broken():
        yield b'data: {"choices":[{"delta":{"content":"par"},"index":0}]}\n\n'
        raise httpx.ReadError("connection reset")

    respx_mock.post(f"{settings.gemini_base_url}/chat/completions").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, content=broken())
    )
    payload = {"model": "fast", "messages": MESSAGES, "stream": True}
    async with client.stream("POST", "/v1/chat/completions", json=payload, headers=auth) as resp:
        raw = b"".join([c async for c in resp.aiter_bytes()]).decode()

    assert '"par"' in raw and '"error"' in raw and "stream interrupted" in raw
    await app.state.log_queue.flush()
    log = (await client.get("/admin/logs", headers=ADMIN_HEADERS)).json()["items"][0]
    assert log["status"] == 502
    model = Upstream(settings.gemini_fast_model, settings.gemini_base_url)
    assert app.state.breakers._state(model).failures == 1


async def test_shared_scope_does_not_coalesce_across_keys(client, auth, create_key, settings, respx_mock) -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, json=COMPLETION)

    route = respx_mock.post(f"{settings.gemini_base_url}/chat/completions").mock(side_effect=slow)
    other = await create_key(rpm=100)
    payload = {"model": "faq", "messages": MESSAGES, "temperature": 0}
    await asyncio.gather(
        client.post("/v1/chat/completions", json=payload, headers=auth),
        client.post("/v1/chat/completions", json=payload, headers={"Authorization": f"Bearer {other['key']}"}),
    )
    assert route.call_count == 2


async def test_cache_write_failure_still_returns_the_answer(client, auth, settings, respx_mock, monkeypatch) -> None:
    respx_mock.post(f"{settings.gemini_base_url}/chat/completions").mock(
        return_value=httpx.Response(200, json=COMPLETION)
    )

    async def broken_admit(*_args, **_kwargs):
        raise RedisConnectionError("cache redis down")

    monkeypatch.setattr(cache, "admit", broken_admit)
    resp = await client.post(
        "/v1/chat/completions", json={"model": "fast", "messages": MESSAGES, "temperature": 0}, headers=auth
    )
    assert resp.status_code == 200 and resp.json() == COMPLETION
    assert resp.headers["x-tollgate-cache"] == "bypass"


def test_half_open_allows_exactly_one_trial() -> None:
    now = [0.0]
    breakers = CircuitBreakers(failure_threshold=1, open_seconds=30, clock=lambda: now[0])
    up = Upstream("m", "http://u")
    breakers.record_failure(up)
    now[0] = 31
    assert breakers.allows(up) is True  # the trial
    assert breakers.allows(up) is False  # concurrent requests wait for its verdict
    assert breakers.is_open(up) is False  # read-only check does not consume the trial
    now[0] = 62  # the trial never reported back: another one is allowed
    assert breakers.allows(up) is True
    breakers.record_success(up)
    assert breakers.allows(up) and breakers.allows(up)


async def test_stream_error_event_is_valid_json(client, auth, settings, respx_mock) -> None:
    async def broken():
        yield b'data: {"choices":[{"delta":{"content":"x"},"index":0}]}\n\n'
        raise httpx.ReadTimeout("slow")

    respx_mock.post(f"{settings.gemini_base_url}/chat/completions").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, content=broken())
    )
    async with client.stream(
        "POST", "/v1/chat/completions", json={"model": "fast", "messages": MESSAGES, "stream": True}, headers=auth
    ) as resp:
        lines = [line async for line in resp.aiter_lines() if line.startswith("data: ")]
    assert json.loads(lines[-1][6:])["error"]["type"] == "upstream_error"
