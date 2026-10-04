"""Forward requests upstream via app.state.http; relay SSE chunks via StreamingResponse."""

import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Upstream
from app.errors import GatewayError

log = logging.getLogger("tollgate.proxy")

CHAT_PATH = "/chat/completions"
_MAX_ERROR_MESSAGE = 500


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge two JSON objects; values in override win."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def build_payload(body: Mapping[str, Any], upstream: Upstream) -> dict[str, Any]:
    payload = deep_merge(upstream.default_params, body)
    payload["model"] = upstream.model
    if payload.get("stream"):
        # Ask for a final usage chunk so token accounting works on streams.
        payload["stream_options"] = {**(payload.get("stream_options") or {}), "include_usage": True}
    return payload


def _upstream_message(response: httpx.Response) -> str:
    """Extract a readable message from OpenAI-style or Gemini-style ([{"error": ...}]) bodies."""
    try:
        data: Any = response.json()
    except ValueError:
        return response.text[:_MAX_ERROR_MESSAGE] or response.reason_phrase
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        error = data.get("error", data)
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:_MAX_ERROR_MESSAGE]
    return response.reason_phrase


def upstream_error(response: httpx.Response, upstream: Upstream) -> GatewayError:
    status = response.status_code
    message = f"upstream {upstream.model}: {_upstream_message(response)}"
    if status in (401, 403):
        # The gateway's upstream credentials are wrong; not the caller's fault.
        return GatewayError(502, "upstream_auth_error", message)
    if status == 429:
        return GatewayError(429, "upstream_rate_limit", message)
    if status >= 500:
        return GatewayError(status, "upstream_error", message)
    return GatewayError(status, "invalid_request_error", message)


def _transport_error(exc: httpx.TransportError, upstream: Upstream) -> GatewayError:
    if isinstance(exc, httpx.TimeoutException):
        return GatewayError(504, "upstream_timeout", f"upstream {upstream.model}: timed out")
    return GatewayError(502, "upstream_unreachable", f"upstream {upstream.model}: {type(exc).__name__}")


def _request(http: httpx.AsyncClient, upstream: Upstream, payload: dict[str, Any]) -> httpx.Request:
    return http.build_request(
        "POST",
        f"{upstream.base_url}{CHAT_PATH}",
        json=payload,
        headers={"Authorization": f"Bearer {upstream.api_key}"} if upstream.api_key else None,
    )


def _log_call(alias: str, upstream: Upstream, status: int, start: float, *, stream: bool, phase: str = "done") -> None:
    log.info(
        "upstream call",
        extra={
            "alias": alias,
            "model": upstream.model,
            "status": status,
            "stream": stream,
            "phase": phase,
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        },
    )


async def complete(http: httpx.AsyncClient, alias: str, upstream: Upstream, payload: dict[str, Any]) -> dict[str, Any]:
    """Non-streaming call. Returns the upstream JSON body or raises GatewayError."""
    start = time.perf_counter()
    try:
        response = await http.send(_request(http, upstream, payload))
    except httpx.TransportError as exc:
        _log_call(alias, upstream, 0, start, stream=False, phase="transport_error")
        raise _transport_error(exc, upstream) from exc

    _log_call(alias, upstream, response.status_code, start, stream=False)
    if response.is_error:
        raise upstream_error(response, upstream)
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise GatewayError(502, "upstream_error", f"upstream {upstream.model}: invalid JSON response") from exc


@dataclass(frozen=True)
class StreamHooks:
    """Synchronous callbacks so they also run when the client disconnects (no awaits needed)."""

    on_chunk: Callable[[bytes], None] | None = None
    on_close: Callable[[], None] | None = None


async def open_stream(
    http: httpx.AsyncClient,
    alias: str,
    upstream: Upstream,
    payload: dict[str, Any],
    hooks: StreamHooks | None = None,
) -> AsyncIterator[bytes]:
    """Start a streaming call and return a byte iterator over the SSE body.

    The upstream status is checked before returning, so failures surface as normal JSON errors
    (with the right status code) instead of a 200 followed by a broken stream.
    """
    start = time.perf_counter()
    try:
        response = await http.send(_request(http, upstream, payload), stream=True)
    except httpx.TransportError as exc:
        _log_call(alias, upstream, 0, start, stream=True, phase="transport_error")
        raise _transport_error(exc, upstream) from exc

    if response.is_error:
        await response.aread()
        await response.aclose()
        _log_call(alias, upstream, response.status_code, start, stream=True)
        raise upstream_error(response, upstream)

    _log_call(alias, upstream, response.status_code, start, stream=True, phase="headers")
    return _relay(response, alias, upstream, start, hooks or StreamHooks())


async def _relay(
    response: httpx.Response, alias: str, upstream: Upstream, start: float, hooks: StreamHooks
) -> AsyncIterator[bytes]:
    """Yield upstream SSE bytes; always release the connection (also on client disconnect).

    aiter_bytes (not aiter_raw) so any upstream gzip is decoded; we don't forward content-encoding.
    """
    try:
        async for chunk in response.aiter_bytes():
            if hooks.on_chunk:
                hooks.on_chunk(chunk)
            yield chunk
    except httpx.TransportError as exc:
        # Headers are already sent; the best we can do is end the stream and log it.
        log.warning("upstream stream broke", extra={"model": upstream.model, "error": repr(exc)})
    finally:
        # on_close first: it is sync, so it runs even if the awaits below are cancelled.
        if hooks.on_close:
            hooks.on_close()
        _log_call(alias, upstream, response.status_code, start, stream=True)
        await response.aclose()
