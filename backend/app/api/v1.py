"""OpenAI-compatible data plane: /v1/chat/completions, /v1/models."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import Alias, Upstream
from app.core import cache, fallback, limits, proxy, tasks, terse, usage
from app.core.coalesce import Flight, Role
from app.core.fair_queue import Ticket
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
    """Pipeline: auth (dependency) -> limits -> cache lookup -> coalescing -> upstream -> after-response."""
    state = request.app.state
    limit = await limits.check(state.redis, key)
    alias = _resolve_alias(request, body.model)

    client_body = body.upstream_body()
    if alias.terse:
        client_body["messages"] = terse.apply(client_body["messages"])
    prompt = usage.prompt_text(client_body["messages"])

    policy = alias.cache
    record.cache_scope = policy.scope
    key_for_cache = None
    if cache.request_eligible(client_body, policy):
        key_for_cache = cache.cache_key(cache.scope_id(policy, str(key.id), body.model), body.model, client_body)
    else:
        record.cache_status = "ineligible"

    ctx = _Context(state, key, record, alias, client_body, prompt, limit, key_for_cache)
    if key_for_cache and (hit := await cache.get(state.redis_cache, key_for_cache)):
        # Hits cost no upstream tokens, so they count against neither the quota nor usage stats.
        record.status, record.model_used, record.cache_hit, record.cache_status = 200, hit.model, True, "hit"
        headers = ctx.hide_if_shared({**limit.headers(), **_tollgate_headers(hit.model, "hit", False)})
        if body.stream:
            replay = cache.render_sse(hit.body)
            record.mark_first_token()

            async def chunks() -> AsyncIterator[bytes]:
                try:
                    for chunk in replay:
                        yield chunk
                finally:
                    _finish(state.log_queue, record)  # streams log when they end

            return StreamingResponse(chunks(), media_type="text/event-stream", headers={**SSE_HEADERS, **headers})
        return JSONResponse(hit.body, headers=headers)
    return await (_stream(ctx) if body.stream else _complete(ctx))


@dataclass(frozen=True)
class _Context:
    state: Any
    key: KeyRecord
    record: RequestRecord
    alias: Alias
    client_body: dict[str, Any]
    prompt: str
    limit: limits.LimitState
    key_for_cache: str | None

    def coalesce_key(self, mode: str) -> str | None:
        """Identical eligible requests share a flight; JSON and SSE responses are separate flights."""
        if self.key_for_cache is None or not self.state.settings.coalescing_enabled:
            return None
        return f"{self.key_for_cache}:{mode}"

    def headers(self, flight: Flight, role: Role) -> dict[str, str]:
        waited = 0 if role == "follower" else flight.queue_wait_ms or 0
        return self.hide_if_shared(
            {
                **self.limit.headers(),
                **_tollgate_headers(flight.model or "", self.record.cache_status or "bypass", flight.fallback_used),
                "x-tollgate-coalesce": role,
                "x-tollgate-queue-wait-ms": str(waited),
            }
        )

    def hide_if_shared(self, headers: dict[str, str]) -> dict[str, str]:
        """In a shared cache pool these headers would tell a caller that someone else asked the same
        thing. (Response timing can still leak it, which is why shared scope is opt-in.)"""
        if self.alias.cache.scope != "shared":
            return headers
        return {k: v for k, v in headers.items() if k not in ("x-tollgate-cache", "x-tollgate-coalesce")}

    @property
    def key_id(self) -> str:
        return str(self.key.id)

    @property
    def fallback_timeout(self) -> float | None:
        """Deadline for attempts that still have a fallback. It includes fair-queue waiting, so a
        saturated model falls back just like a slow one."""
        return self.state.settings.fallback_timeout or None

    def waited(self, flight: Flight, ticket: Ticket | None) -> None:
        if ticket is not None:
            flight.queue_wait_ms = (flight.queue_wait_ms or 0) + ticket.wait_ms


def _apply_flight(record: RequestRecord, flight: Flight, role: Role) -> None:
    record.coalesce_role = role
    record.model_used, record.fallback_used = flight.model, flight.fallback_used
    # Followers never waited for a model slot or ran the upstream call themselves.
    record.queue_wait_ms = flight.queue_wait_ms if role != "follower" else None


async def _complete(ctx: _Context) -> JSONResponse:
    state, record = ctx.state, ctx.record

    queue = state.fair_queue

    async def lead(flight: Flight) -> dict[str, Any]:
        async def call(upstream: Upstream) -> dict[str, Any]:
            payload = proxy.build_payload(ctx.client_body, upstream)
            async with queue.slot(upstream.model, ctx.key_id, ctx.key.prefix) as ticket:
                ctx.waited(flight, ticket)
                queue.charge(ctx.key_id, input_tokens=usage.estimate_tokens(ctx.prompt))
                value = await proxy.complete(state.http, record.alias, upstream, payload)
                queue.charge(ctx.key_id, output_tokens=usage.from_completion(value, ctx.prompt).completion_tokens)
                return value

        result = await fallback.run_chain(record.alias, ctx.alias.chain, state.breakers, call, ctx.fallback_timeout)
        flight.set_meta(result.upstream.model, result.fallback_used)
        if ctx.key_for_cache:
            flight.cache_status = await _store(ctx, result.upstream.model, result.value, flight)
        return result.value

    flight, role = state.coalescer.join(ctx.coalesce_key("json"), lead)
    try:
        value = await flight.wait_result()
    finally:
        state.coalescer.leave(flight)

    _apply_flight(record, flight, role)
    used = usage.from_completion(value, ctx.prompt)  # every receiver pays for what it received
    record.status, record.usage = 200, used
    if ctx.key_for_cache:
        record.cache_status = "miss" if role == "follower" else flight.cache_status
    await limits.record_tokens(state.redis, ctx.key.id, used.total_tokens)
    # Upstream JSON is already OpenAI-shaped; skip FastAPI's re-encoding pass.
    return JSONResponse(value, headers=ctx.headers(flight, role))


async def _store(ctx: _Context, model: str, body: dict[str, Any] | None, flight: Flight) -> cache.CacheStatus:
    """Cache a fresh response if it is complete, small enough and popular: seen before (second sight)
    or already shared by two or more coalesced followers. Shared scope also spends insert budget."""
    state, policy, key_for_cache = ctx.state, ctx.alias.cache, ctx.key_for_cache
    assert key_for_cache is not None
    settings = state.settings
    encoded = cache.encode_if_eligible(model, body, settings.cache_max_entry_bytes) if body else None
    if encoded is None:
        return "ineligible"
    popular = flight.followers >= 2
    if not popular and not await cache.admit(state.redis_cache, key_for_cache, settings.cache_seen_ttl):
        return "admission_rejected"
    if policy.scope == "shared" and not await cache.within_insert_budget(
        state.redis, ctx.key_id, policy.insert_budget_per_min
    ):
        return "admission_rejected"  # served normally, just not added to the shared pool
    await cache.put(state.redis_cache, key_for_cache, encoded, policy.ttl_seconds)
    return "miss"


async def _stream(ctx: _Context) -> StreamingResponse:
    state, record = ctx.state, ctx.record

    queue = state.fair_queue

    async def lead(flight: Flight) -> None:
        async def open_(upstream: Upstream) -> tuple[AsyncIterator[bytes], Ticket | None]:
            payload = proxy.build_payload(ctx.client_body, upstream)
            ticket = await queue.acquire(upstream.model, ctx.key_id, ctx.key.prefix)
            ctx.waited(flight, ticket)
            queue.charge(ctx.key_id, input_tokens=usage.estimate_tokens(ctx.prompt))
            try:
                return await proxy.open_stream(state.http, record.alias, upstream, payload), ticket
            except BaseException:
                queue.release(upstream.model, ticket)
                raise

        # Fallback is possible until the first byte: open_stream checks the upstream status first.
        streamed = await fallback.run_chain(record.alias, ctx.alias.chain, state.breakers, open_, ctx.fallback_timeout)
        chunks, ticket = streamed.value
        flight.set_meta(streamed.upstream.model, streamed.fallback_used)
        meter = usage.SSEUsageTracker(ctx.prompt)
        try:  # the model slot is held until the stream ends
            async for chunk in chunks:
                before = meter.content_chars
                meter.feed(chunk)
                queue.charge(ctx.key_id, output_tokens=(meter.content_chars - before) / 4)
                await flight.emit(chunk)
        finally:
            queue.release(streamed.upstream.model, ticket)
        if ctx.key_for_cache:
            meter.result()  # flush a trailing partial line
            body = cache.completion_from_stream(meter, streamed.upstream.model)
            flight.cache_status = await _store(ctx, streamed.upstream.model, body, flight)

    flight, role = state.coalescer.join(ctx.coalesce_key("sse"), lead)
    try:
        await flight.wait_ready()
    except BaseException:
        state.coalescer.leave(flight)
        raise
    _apply_flight(record, flight, role)
    if ctx.key_for_cache:
        record.cache_status = "miss"  # header value; the final status (stored or not) is logged at the end
    tracker = usage.SSEUsageTracker(ctx.prompt)

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in flight.replay():
                tracker.feed(chunk)
                if tracker.content_seen:
                    record.mark_first_token()
                yield chunk
        finally:
            # Synchronous only: this also runs when the client disconnects (cancellation).
            state.coalescer.leave(flight)
            if ctx.key_for_cache:
                record.cache_status = "miss" if role == "follower" else (flight.cache_status or "miss")
            record.status, record.usage = 200, tracker.result()
            _finish(state.log_queue, record)
            tasks.spawn(limits.record_tokens(state.redis, ctx.key.id, record.usage.total_tokens), name="tokens")

    return StreamingResponse(
        body(), media_type="text/event-stream", headers={**SSE_HEADERS, **ctx.headers(flight, role)}
    )


@router.get("/models")
async def list_models(request: Request) -> ModelList:
    return ModelList(data=[ModelCard(id=name) for name in request.app.state.aliases])


@router.get("/models/{model_id}")
async def get_model(model_id: str, request: Request) -> ModelCard:
    _resolve_alias(request, model_id)
    return ModelCard(id=model_id)
