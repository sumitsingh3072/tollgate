"""OpenAI-compatible data plane: /v1/chat/completions, /v1/models."""

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import Alias, Upstream
from app.core import cache, fallback, limits, proxy, tasks, terse, usage
from app.core.keys import KeyRecord
from app.deps import require_api_key
from app.errors import GatewayError
from app.schemas import ChatCompletionRequest, ModelCard, ModelList

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


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionRequest, request: Request, key: KeyRecord = Depends(require_api_key)
) -> JSONResponse | StreamingResponse:
    state = request.app.state
    limit = await limits.check(state.redis, key)
    alias = _resolve_alias(request, body.model)

    client_body = body.upstream_body()
    if alias.terse:
        client_body["messages"] = terse.apply(client_body["messages"])
    prompt = usage.prompt_text(client_body["messages"])

    if body.stream:
        tracker = usage.SSEUsageTracker(prompt)

        def on_close() -> None:
            tokens = tracker.result().total_tokens
            tasks.spawn(limits.record_tokens(state.redis, key.id, tokens), name="record-tokens")

        hooks = proxy.StreamHooks(on_chunk=tracker.feed, on_close=on_close)

        async def open_stream(upstream: Upstream) -> AsyncIterator[bytes]:
            payload = proxy.build_payload(client_body, upstream)
            return await proxy.open_stream(state.http, body.model, upstream, payload, hooks)

        # Fallback is possible until the first byte: open_stream checks the upstream status first.
        streamed = await fallback.run_chain(body.model, alias.chain, state.breakers, open_stream)
        headers = {
            **SSE_HEADERS,
            **limit.headers(),
            **_tollgate_headers(streamed.upstream.model, "bypass", streamed.fallback_used),
        }
        return StreamingResponse(streamed.value, media_type="text/event-stream", headers=headers)

    key_for_cache = cache.cache_key(client_body) if cache.is_cacheable(client_body) else None
    if key_for_cache and (hit := await cache.get(state.redis, key_for_cache)):
        # Hits cost no upstream tokens, so they don't count against the daily quota.
        return JSONResponse(hit.body, headers={**limit.headers(), **_tollgate_headers(hit.model, "hit", False)})

    async def complete(upstream: Upstream) -> dict[str, Any]:
        return await proxy.complete(state.http, body.model, upstream, proxy.build_payload(client_body, upstream))

    result = await fallback.run_chain(body.model, alias.chain, state.breakers, complete)
    await limits.record_tokens(state.redis, key.id, usage.from_completion(result.value, prompt).total_tokens)
    if key_for_cache:
        await cache.put(state.redis, key_for_cache, result.upstream.model, result.value, state.settings.cache_ttl)

    headers = {
        **limit.headers(),
        **_tollgate_headers(result.upstream.model, "miss" if key_for_cache else "bypass", result.fallback_used),
    }
    # Upstream JSON is already OpenAI-shaped; skip FastAPI's re-encoding pass.
    return JSONResponse(result.value, headers=headers)


@router.get("/models")
async def list_models(request: Request) -> ModelList:
    return ModelList(data=[ModelCard(id=name) for name in request.app.state.aliases])


@router.get("/models/{model_id}")
async def get_model(model_id: str, request: Request) -> ModelCard:
    _resolve_alias(request, model_id)
    return ModelCard(id=model_id)
