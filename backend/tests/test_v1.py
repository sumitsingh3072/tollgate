import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from app.config import Settings

pytestmark = pytest.mark.respx(assert_all_called=False)

MESSAGES = [{"role": "user", "content": "hi"}]
COMPLETION = {
    "id": "c1",
    "object": "chat.completion",
    "model": "gemma-4-31b-it",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}
SSE_EVENTS = [
    b'data: {"choices":[{"delta":{"role":"assistant","content":"Hel"},"index":0}]}\n\n',
    b'data: {"choices":[{"delta":{"content":"lo"},"index":0}]}\n\n',
    b'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}\n\n',
    b"data: [DONE]\n\n",
]


def chat_url(settings: Settings) -> str:
    return f"{settings.gemini_base_url}/chat/completions"


async def sse_body() -> AsyncIterator[bytes]:
    for event in SSE_EVENTS:
        yield event


async def test_non_stream_forwards_to_first_model(
    client: httpx.AsyncClient, auth: dict[str, str], settings: Settings, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post(chat_url(settings)).mock(return_value=httpx.Response(200, json=COMPLETION))

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "smart", "messages": MESSAGES, "temperature": 0, "top_p": 0.9},
        headers=auth,
    )

    assert resp.status_code == 200
    assert resp.json() == COMPLETION
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer test-key"  # upstream key, never the client's
    body = json.loads(sent.content)
    assert body["model"] == settings.gemini_smart_model
    assert body["top_p"] == 0.9  # unknown OpenAI fields pass through
    assert body["extra_body"]["google"]["thinking_config"]["thinking_level"] == "minimal"
    assert "stream" not in body  # nothing the client didn't send


async def test_client_extra_body_overrides_defaults(
    client: httpx.AsyncClient, auth: dict[str, str], settings: Settings, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post(chat_url(settings)).mock(return_value=httpx.Response(200, json=COMPLETION))
    extra = {"google": {"thinking_config": {"thinking_level": "high"}}}

    await client.post(
        "/v1/chat/completions", json={"model": "fast", "messages": MESSAGES, "extra_body": extra}, headers=auth
    )

    body = json.loads(route.calls.last.request.content)
    assert body["model"] == settings.gemini_fast_model
    assert body["extra_body"] == extra


async def test_stream_relays_chunks_in_order(
    client: httpx.AsyncClient, auth: dict[str, str], settings: Settings, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post(chat_url(settings)).mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse_body())
    )

    async with client.stream(
        "POST", "/v1/chat/completions", json={"model": "fast", "messages": MESSAGES, "stream": True}, headers=auth
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        lines = [line async for line in resp.aiter_lines() if line]

    assert lines == [event.decode().strip() for event in SSE_EVENTS]
    body = json.loads(route.calls.last.request.content)
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}


async def test_stream_upstream_error_returns_json_status(
    client: httpx.AsyncClient, auth: dict[str, str], settings: Settings, respx_mock: respx.MockRouter
) -> None:
    gemini_error = [{"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}}]
    respx_mock.post(chat_url(settings)).mock(return_value=httpx.Response(503, json=gemini_error))

    resp = await client.post(
        "/v1/chat/completions", json={"model": "fast", "messages": MESSAGES, "stream": True}, headers=auth
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["type"] == "upstream_error"
    assert "high demand" in resp.json()["error"]["message"]


@pytest.mark.parametrize(
    ("upstream_status", "status", "type_"),
    [
        (400, 400, "invalid_request_error"),
        (401, 502, "upstream_auth_error"),
        (403, 502, "upstream_auth_error"),
        (404, 404, "invalid_request_error"),
        (429, 429, "upstream_rate_limit"),
        (500, 500, "upstream_error"),
        (503, 503, "upstream_error"),
    ],
)
async def test_upstream_errors_mapped_to_openai_envelope(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    settings: Settings,
    respx_mock: respx.MockRouter,
    upstream_status: int,
    status: int,
    type_: str,
) -> None:
    gemini_error = [{"error": {"code": upstream_status, "message": "boom", "status": "X"}}]
    respx_mock.post(chat_url(settings)).mock(return_value=httpx.Response(upstream_status, json=gemini_error))

    resp = await client.post("/v1/chat/completions", json={"model": "fast", "messages": MESSAGES}, headers=auth)

    assert resp.status_code == status
    assert resp.json() == {"error": {"type": type_, "message": f"upstream {settings.gemini_fast_model}: boom"}}


@pytest.mark.parametrize(
    ("exc", "status", "type_"),
    [(httpx.ReadTimeout("slow"), 504, "upstream_timeout"), (httpx.ConnectError("down"), 502, "upstream_unreachable")],
)
async def test_transport_errors(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    settings: Settings,
    respx_mock: respx.MockRouter,
    exc: Exception,
    status: int,
    type_: str,
) -> None:
    respx_mock.post(chat_url(settings)).mock(side_effect=exc)

    resp = await client.post("/v1/chat/completions", json={"model": "fast", "messages": MESSAGES}, headers=auth)

    assert resp.status_code == status
    assert resp.json()["error"]["type"] == type_


async def test_unknown_alias_is_404(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    resp = await client.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": MESSAGES}, headers=auth)

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "model_not_found"


@pytest.mark.parametrize(
    "payload",
    [
        {"model": "fast", "messages": []},
        {"model": "fast"},
        {"model": "fast", "messages": [{"role": "wizard", "content": "x"}]},
        {"model": "fast", "messages": MESSAGES, "temperature": 5},
    ],
)
async def test_invalid_requests_are_422(client: httpx.AsyncClient, auth: dict[str, str], payload: dict) -> None:
    resp = await client.post("/v1/chat/completions", json=payload, headers=auth)

    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "invalid_request_error"


async def test_list_models(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    resp = await client.get("/v1/models", headers=auth)

    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert [m["id"] for m in body["data"]] == ["fast", "smart", "smart-terse"]


async def test_get_model(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    ok = await client.get("/v1/models/smart", headers=auth)
    missing = await client.get("/v1/models/nope", headers=auth)

    assert ok.json()["id"] == "smart"
    assert missing.status_code == 404
