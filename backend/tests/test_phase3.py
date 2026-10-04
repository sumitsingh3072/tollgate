import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from app.config import Settings, Upstream
from app.core import fallback, terse
from app.core.fallback import CircuitBreakers

pytestmark = pytest.mark.respx(assert_all_called=False)

MESSAGES = [{"role": "user", "content": "hi"}]


def completion(model: str = "gemma", total: int = 5) -> dict:
    return {
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": total},
    }


@pytest.fixture
def gemini(settings: Settings, respx_mock: respx.MockRouter) -> respx.Route:
    return respx_mock.post(f"{settings.gemini_base_url}/chat/completions")


@pytest.fixture
def mock_upstream(settings: Settings, respx_mock: respx.MockRouter) -> respx.Route:
    return respx_mock.post(f"{settings.mock_upstream_url}/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": {"message": "mock failure"}})
    )


async def post(client: httpx.AsyncClient, auth: dict[str, str], **body) -> httpx.Response:
    return await client.post("/v1/chat/completions", json={"messages": MESSAGES, **body}, headers=auth)


# --- fallback + circuit breaker -------------------------------------------------------------


async def test_demo_failover_falls_back_cleanly(client, auth, gemini, mock_upstream, settings: Settings) -> None:
    gemini.mock(return_value=httpx.Response(200, json=completion()))

    resp = await post(client, auth, model="demo-failover")

    assert resp.status_code == 200
    assert resp.headers["x-tollgate-fallback"] == "true"
    assert resp.headers["x-tollgate-model"] == settings.gemini_fast_model
    assert mock_upstream.call_count == 1
    assert "authorization" not in mock_upstream.calls.last.request.headers  # keyless upstream


async def test_smart_falls_back_on_503_and_timeout(client, auth, gemini, settings: Settings) -> None:
    def by_model(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"] == settings.gemini_smart_model:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, json=completion(settings.gemini_fast_model))

    gemini.mock(side_effect=by_model)

    resp = await post(client, auth, model="smart")

    assert resp.status_code == 200
    assert resp.headers["x-tollgate-fallback"] == "true"
    assert resp.headers["x-tollgate-model"] == settings.gemini_fast_model


async def test_slow_upstream_falls_back_after_fallback_timeout() -> None:
    breakers = CircuitBreakers(3, 30.0)
    smart, fast = Upstream("smart-model", "http://up"), Upstream("fast-model", "http://up")

    async def attempt(upstream: Upstream) -> str:
        if upstream is smart:
            await asyncio.sleep(10)
        return upstream.model

    result = await fallback.run_chain("smart", (smart, fast), breakers, attempt, fallback_timeout=0.05)

    assert result.value == "fast-model"
    assert result.fallback_used


async def test_stream_falls_back_when_first_byte_is_slow(client, auth, gemini, settings: Settings) -> None:
    settings.fallback_timeout = 0.05

    async def sse() -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"fast"},"index":0}]}\n\ndata: [DONE]\n\n'

    async def by_model(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"] == settings.gemini_smart_model:
            await asyncio.sleep(10)  # Gemini holds headers until the first token
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse())

    gemini.mock(side_effect=by_model)

    body = {"model": "smart", "messages": MESSAGES, "stream": True}
    async with client.stream("POST", "/v1/chat/completions", json=body, headers=auth) as resp:
        raw = b"".join([chunk async for chunk in resp.aiter_bytes()])

    assert resp.status_code == 200
    assert resp.headers["x-tollgate-fallback"] == "true"
    assert resp.headers["x-tollgate-model"] == settings.gemini_fast_model
    assert b'"fast"' in raw


async def test_fallback_timeout_does_not_apply_to_last_upstream() -> None:
    only = Upstream("only-model", "http://up")

    async def attempt(upstream: Upstream) -> str:
        await asyncio.sleep(0.1)
        return upstream.model

    result = await fallback.run_chain("fast", (only,), CircuitBreakers(3, 30.0), attempt, fallback_timeout=0.01)

    assert result.value == "only-model"


async def test_client_errors_do_not_fall_back(client, auth, gemini) -> None:
    gemini.mock(return_value=httpx.Response(400, json=[{"error": {"message": "bad request"}}]))

    resp = await post(client, auth, model="smart")

    assert resp.status_code == 400
    assert gemini.call_count == 1


async def test_all_upstreams_fail_returns_last_error(client, auth, gemini, mock_upstream) -> None:
    gemini.mock(return_value=httpx.Response(503, json=[{"error": {"message": "high demand"}}]))

    resp = await post(client, auth, model="demo-failover")

    assert resp.status_code == 503
    assert "high demand" in resp.json()["error"]["message"]


async def test_breaker_skips_failing_upstream(client, auth, gemini, mock_upstream) -> None:
    gemini.mock(return_value=httpx.Response(200, json=completion()))

    for _ in range(5):
        assert (await post(client, auth, model="demo-failover")).status_code == 200

    assert mock_upstream.call_count == 3  # opened after 3 failures, then skipped


async def test_stream_falls_back_before_first_byte(client, auth, gemini, mock_upstream, settings: Settings) -> None:
    async def sse() -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"ok"},"index":0}]}\n\ndata: [DONE]\n\n'

    gemini.mock(return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse()))

    body = {"model": "demo-failover", "messages": MESSAGES, "stream": True}
    async with client.stream("POST", "/v1/chat/completions", json=body, headers=auth) as resp:
        raw = b"".join([chunk async for chunk in resp.aiter_bytes()])

    assert resp.status_code == 200
    assert resp.headers["x-tollgate-fallback"] == "true"
    assert resp.headers["x-tollgate-model"] == settings.gemini_fast_model
    assert b'"ok"' in raw


def test_breaker_half_open_cycle() -> None:
    now = [0.0]
    breakers = CircuitBreakers(failure_threshold=3, open_seconds=30, clock=lambda: now[0])
    up = Upstream("m", "http://u")

    for _ in range(3):
        breakers.record_failure(up)
    assert breakers.is_open(up)

    now[0] = 31
    assert breakers.allows(up)  # half-open trial
    breakers.record_failure(up)
    assert breakers.is_open(up)  # trial failed, re-opened

    now[0] = 62
    breakers.record_success(up)
    assert breakers.allows(up)
    breakers.record_failure(up)
    assert breakers.allows(up)  # counter was reset


# --- terse ------------------------------------------------------------------------------------


async def test_terse_alias_injects_system_prompt(client, auth, gemini) -> None:
    gemini.mock(return_value=httpx.Response(200, json=completion()))

    await post(client, auth, model="smart-terse")
    await post(client, auth, model="smart")

    terse_body, normal_body = (json.loads(call.request.content) for call in gemini.calls)
    assert terse_body["messages"][0] == {"role": "system", "content": terse.TERSE_PROMPT}
    assert normal_body["messages"] == MESSAGES


def test_terse_merges_existing_system_message() -> None:
    messages = [{"role": "system", "content": "You are a bot."}, {"role": "user", "content": "hi"}]
    merged = terse.apply(messages)
    assert len(merged) == 2
    assert merged[0]["content"] == f"{terse.TERSE_PROMPT}\n\nYou are a bot."
    assert messages[0]["content"] == "You are a bot."  # input untouched
