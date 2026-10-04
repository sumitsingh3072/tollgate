"""OpenAI-compatible data plane: /v1/chat/completions, /v1/models."""

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import Alias, Upstream
from app.core import cache, fallback, limits, proxy, tasks, terse, usage
from app.core.keys import KeyRecord
from app.core.tags import TAGS_HEADER, parse_tags
from app.deps import require_api_key
from app.errors import DEPENDENCY_ERRORS, GatewayError
from app.logging_queue import LogQueue, RequestRecord
from app.schemas import ChatCompletionRequest, ModelCard, ModelList
from app.telemetry import metrics

router = APIRouter(prefix="/v1", tags=["v1"], dependencies=[Depends(require_api_key)])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _resolve_alias(request: Request, name: str) -> Alias:
    aliases: dict[str, Alias] = request.app.state.aliases
    alias = aliases.get(name)
    if alias is None:
        raise GatewayError(
            404,
            "invalid_request_error",
            f"model '{name}' not found; available: {', '.join(aliases)}",
            code="model_not_found",
        )
    return alias


def _tollgate_headers(model: str, cache_status: str, fallback_used: bool) -> dict[str, str]:
    return {
        "x-tollgate-model": model,
        "x-tollgate-cache": cache_status,
        "x-tollgate-fallback": "true" if fallback_used else "false",
    }


def _status_for(exc: Exception) -> int:
    if isinstance(exc, GatewayError):
        return exc.status_code
    return 503 if isinstance(exc, DEPENDENCY_ERRORS) else 500


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionRequest, request: Request, key: KeyRecord = Depends(require_api_key)
) -> JSONResponse | StreamingResponse:
    """Every authenticated request produces exactly one log event (streams log when they end)."""
    record = RequestRecord(key_id=key.id, alias=body.model, tags=parse_tags(request.headers.get(TAGS_HEADER)))
    try:
        response = await _handle(body, request, key, record)
    except Exception as exc:
        record.status = _status_for(exc)
        _finish(request.app.state.log_queue, record)
        raise
    if not isinstance(response, StreamingResponse):
        _finish(request.app.state.log_queue, record)
    return response


def _finish(log_queue: LogQueue, record: RequestRecord) -> None:
    event = record.finish()
    log_queue.enqueue(event)
    metrics.observe(event)


async def _handle(
    body: ChatCompletionRequest, request: Request, key: KeyRecord, record: RequestRecord
) -> JSONResponse | StreamingResponse:
    state = request.app.state
    limit = await limits.check(state.redis, key)
    alias = _resolve_alias(request, body.model)

    client_body = body.upstream_body()
    if alias.terse:
        client_body["messages"] = terse.apply(client_body["messages"])
    prompt = usage.prompt_text(client_body["messages"])

    policy = alias.cache
    record.cache_scope = policy.scope
    if body.stream:
        record.cache_status = "bypass"  # streamed responses are not cached yet
        return await _stream(request, key, record, alias, client_body, prompt, limit)

    key_for_cache = None
    if cache.request_eligible(client_body, policy):
        scope = cache.scope_id(policy, str(key.id), body.model)
        key_for_cache = cache.cache_key(scope, body.model, client_body)
    else:
        record.cache_status = "ineligible"
    if key_for_cache and (hit := await cache.get(state.redis_cache, key_for_cache)):
        # Hits cost no upstream tokens, so they count against neither the quota nor usage stats.
        record.status, record.model_used, record.cache_hit, record.cache_status = 200, hit.model, True, "hit"
        return JSONResponse(hit.body, headers={**limit.headers(), **_tollgate_headers(hit.model, "hit", False)})

    async def complete(upstream: Upstream) -> dict[str, Any]:
        return await proxy.complete(state.http, body.model, upstream, proxy.build_payload(client_body, upstream))

    result = await fallback.run_chain(body.model, alias.chain, state.breakers, complete)
    used = usage.from_completion(result.value, prompt)
    record.status, record.model_used, record.fallback_used, record.usage = (
        200,
        result.upstream.model,
        result.fallback_used,
        used,
    )
    await limits.record_tokens(state.redis, key.id, used.total_tokens)
    if key_for_cache:
        record.cache_status = await _store(state, key_for_cache, result.upstream.model, result.value, policy)

    headers = {
        **limit.headers(),
        **_tollgate_headers(result.upstream.model, record.cache_status or "bypass", result.fallback_used),
    }
    # Upstream JSON is already OpenAI-shaped; skip FastAPI's re-encoding pass.
    return JSONResponse(result.value, headers=headers)


async def _store(
    state: Any, key_for_cache: str, model: str, body: dict[str, Any], policy: cache.CachePolicy
) -> cache.CacheStatus:
    """Cache a fresh response if it is complete, small enough and seen before (second sight)."""
    settings = state.settings
    encoded = cache.encode_if_eligible(model, body, settings.cache_max_entry_bytes)
    if encoded is None:
        return "ineligible"
    if not await cache.admit(state.redis_cache, key_for_cache, settings.cache_seen_ttl):
        return "admission_rejected"
    await cache.put(state.redis_cache, key_for_cache, encoded, policy.ttl_seconds)
    return "miss"


async def _stream(
    request: Request,
    key: KeyRecord,
    record: RequestRecord,
    alias: Alias,
    client_body: dict[str, Any],
    prompt: str,
    limit: limits.LimitState,
) -> StreamingResponse:
    state = request.app.state
    tracker = usage.SSEUsageTracker(prompt)

    def on_chunk(chunk: bytes) -> None:
        tracker.feed(chunk)
        if tracker.content_seen:
            record.mark_first_token()

    def on_close() -> None:
        record.status, record.usage = 200, tracker.result()
        _finish(state.log_queue, record)
        tasks.spawn(limits.record_tokens(state.redis, key.id, record.usage.total_tokens), name="record-tokens")

    hooks = proxy.StreamHooks(on_chunk=on_chunk, on_close=on_close)

    async def open_stream(upstream: Upstream) -> AsyncIterator[bytes]:
        payload = proxy.build_payload(client_body, upstream)
        return await proxy.open_stream(state.http, record.alias, upstream, payload, hooks)

    # Fallback is possible until the first byte: open_stream checks the upstream status first.
    streamed = await fallback.run_chain(record.alias, alias.chain, state.breakers, open_stream)
    record.model_used, record.fallback_used = streamed.upstream.model, streamed.fallback_used
    headers = {
        **SSE_HEADERS,
        **limit.headers(),
        **_tollgate_headers(streamed.upstream.model, "bypass", streamed.fallback_used),
    }
    return StreamingResponse(streamed.value, media_type="text/event-stream", headers=headers)


@router.get("/models")
async def list_models(request: Request) -> ModelList:
    return ModelList(data=[ModelCard(id=name) for name in request.app.state.aliases])


@router.get("/models/{model_id}")
async def get_model(model_id: str, request: Request) -> ModelCard:
    _resolve_alias(request, model_id)
    return ModelCard(id=model_id)
