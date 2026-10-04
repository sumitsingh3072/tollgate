"""Control plane: /admin/keys, /admin/stats, /admin/logs. Phases 2 and 4."""

import logging
import uuid
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status

from app.config import Settings
from app.core import keys, limits
from app.db import analytics, queries
from app.db.models import RequestLog
from app.deps import AdminScope, admin_scope, require_admin
from app.errors import GatewayError
from app.schemas import (
    ActivityDay,
    AliasOut,
    CoalesceStats,
    GroupUsage,
    KeyCreate,
    KeyCreated,
    KeyOut,
    KeyUsage,
    LatencyBin,
    LogOut,
    LogPage,
    Me,
    PeriodTotals,
    SeriesPoint,
    Stats,
    StatusMix,
    UserLimits,
)

log = logging.getLogger("tollgate.admin")

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _enforce_user_caps(body: KeyCreate, settings: Settings, active_keys: int) -> None:
    """Self-serve users share the gateway's upstream budget, so their keys are capped."""
    if active_keys >= settings.user_max_keys:
        raise GatewayError(
            403, "key_limit", f"You can have at most {settings.user_max_keys} active keys. Revoke one first."
        )
    if body.rpm > settings.user_max_rpm:
        raise GatewayError(422, "invalid_request_error", f"rpm: at most {settings.user_max_rpm} requests per minute.")
    if body.daily_token_quota > settings.user_max_daily_tokens:
        raise GatewayError(
            422,
            "invalid_request_error",
            f"daily_token_quota: at most {settings.user_max_daily_tokens:,} tokens per day.",
        )


@router.post("/keys", status_code=status.HTTP_201_CREATED)
async def create_key(body: KeyCreate, request: Request, scope: AdminScope = Depends(admin_scope)) -> KeyCreated:
    raw = keys.generate_key()
    key_hash = keys.hash_key(raw)
    async with request.app.state.sessionmaker() as session:
        if not scope.is_operator:
            _enforce_user_caps(
                body, request.app.state.settings, await queries.count_active_keys(session, scope.owner_id)
            )
        row = await queries.create_key(
            session,
            name=body.name,
            key_hash=key_hash,
            prefix=raw[: keys.DISPLAY_PREFIX_LENGTH],
            rpm=body.rpm,
            daily_token_quota=body.daily_token_quota,
            owner_id=scope.owner_id,
        )
    # Overwrite any negative cache entry so the key works immediately.
    record = keys.KeyRecord(id=row.id, name=row.name, rpm=row.rpm, daily_token_quota=row.daily_token_quota)
    await keys.cache_set(request.app.state.redis, key_hash, record, request.app.state.settings.key_cache_ttl)
    log.info("key created", extra={"key_id": str(row.id), "prefix": row.prefix, "owner": scope.owner_id or "operator"})
    return KeyCreated(**KeyOut.model_validate(row).model_dump(), key=raw)


@router.get("/keys")
async def list_keys(request: Request, scope: AdminScope = Depends(admin_scope)) -> list[KeyOut]:
    async with request.app.state.sessionmaker() as session:
        rows = await queries.list_keys(session, scope.owner_id)
    usage = await limits.tokens_today(request.app.state.redis, [r.id for r in rows if r.revoked_at is None])
    return [KeyOut.model_validate(r).model_copy(update={"tokens_today": usage.get(r.id, 0)}) for r in rows]


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: uuid.UUID, request: Request, scope: AdminScope = Depends(admin_scope)) -> KeyOut:
    async with request.app.state.sessionmaker() as session:
        row = await queries.revoke_key(session, key_id, scope.owner_id)
    if row is None:
        raise GatewayError(404, "not_found", f"key {key_id} not found")
    await keys.cache_delete(request.app.state.redis, row.key_hash)
    log.info("key revoked", extra={"key_id": str(row.id), "prefix": row.prefix})
    return KeyOut.model_validate(row)


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def _period(t: analytics.Totals) -> dict[str, Any]:
    return {
        "requests": t.requests,
        "errors": t.errors,
        "error_rate": _rate(t.errors, t.requests),
        "cache_hits": t.cache_hits,
        "cache_hit_rate": _rate(t.cache_hits, t.requests),
        "fallbacks": t.fallbacks,
        "in_tokens": t.in_tokens,
        "out_tokens": t.out_tokens,
        "p50_latency_ms": t.p50_latency_ms,
        "p95_latency_ms": t.p95_latency_ms,
    }


def _histogram(counts: list[int]) -> list[LatencyBin]:
    bounds = (0, *analytics.LATENCY_BINS_MS)
    uppers = (*analytics.LATENCY_BINS_MS, None)
    return [LatencyBin(lower_ms=lo, upper_ms=hi, count=n) for lo, hi, n in zip(bounds, uppers, counts, strict=True)]


@router.get("/stats")
async def stats(
    request: Request,
    hours: int = Query(default=24, ge=1, le=24 * 30),
    scope: AdminScope = Depends(admin_scope),
) -> Stats:
    window = analytics.Window.last(hours, owner_id=scope.owner_id)
    bucket = analytics.bucket_seconds(window)
    current, previous, series, by_key, by_alias, by_model = await analytics.run_concurrently(
        request.app.state.sessionmaker,
        lambda s: analytics.totals(s, window),
        lambda s: analytics.totals(s, window.previous()),
        lambda s: analytics.timeseries(s, window, bucket),
        lambda s: analytics.usage_by_key(s, window),
        lambda s: analytics.usage_by_alias(s, window),
        lambda s: analytics.usage_by_model(s, window),
    )
    return Stats(
        **_period(current),
        window_hours=hours,
        previous=PeriodTotals(**_period(previous)),
        status_mix=StatusMix(**asdict(current.status_mix)),
        latency_histogram=_histogram(current.latency_histogram),
        bucket_seconds=bucket,
        series=[SeriesPoint(**asdict(p)) for p in series],
        by_key=[KeyUsage(**asdict(row)) for row in by_key],
        by_alias=[GroupUsage(**asdict(row)) for row in by_alias],
        by_model=[GroupUsage(**asdict(row)) for row in by_model],
    )


@router.get("/coalesce/stats")
async def coalesce_stats(
    request: Request,
    hours: int = Query(default=24, ge=1, le=24 * 30),
    scope: AdminScope = Depends(admin_scope),
) -> CoalesceStats:
    window = analytics.Window.last(hours, owner_id=scope.owner_id)
    async with request.app.state.sessionmaker() as session:
        roles = await analytics.counts_by(session, window, RequestLog.coalesce_role)
    leaders, followers = roles.get("leader", 0), roles.get("follower", 0)
    coalescer = request.app.state.coalescer
    return CoalesceStats(
        window_hours=hours,
        leaders=leaders,
        followers=followers,
        calls_saved=followers,
        share_rate=_rate(followers, leaders + followers),
        in_flight=coalescer.in_flight,
        largest_fanout_since_start=coalescer.stats.largest_fanout,
        flights_since_start=coalescer.stats.flights,
    )


@router.get("/activity")
async def activity(
    request: Request,
    days: int = Query(default=365, ge=7, le=366),
    scope: AdminScope = Depends(admin_scope),
) -> list[ActivityDay]:
    """Daily totals (UTC) for a contribution-style heatmap; days with no traffic are included as zeros."""
    window = analytics.Window.last(days * 24, owner_id=scope.owner_id)
    async with request.app.state.sessionmaker() as session:
        points = await analytics.timeseries(session, window, analytics.DAY_SECONDS)
    return [
        ActivityDay(date=f"{p.ts:%Y-%m-%d}", requests=p.requests, tokens=p.in_tokens + p.out_tokens, errors=p.errors)
        for p in points
    ]


@router.get("/logs")
async def logs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    before: int | None = Query(default=None, ge=1, description="Cursor from a previous page's next_cursor."),
    key_id: uuid.UUID | None = None,
    alias: str | None = None,
    status_code: int | None = Query(default=None, alias="status", ge=100, le=599),
    errors_only: bool = False,
    cache_status: str | None = Query(default=None, pattern="^(hit|miss|admission_rejected|ineligible|bypass)$"),
    coalesce_role: str | None = Query(default=None, pattern="^(none|leader|follower)$"),
    tag: str | None = Query(
        default=None, pattern=r"^[A-Za-z0-9_.-]{1,64}=[A-Za-z0-9_.-]{1,64}$", description="key=value"
    ),
    scope: AdminScope = Depends(admin_scope),
) -> LogPage:
    filters = queries.LogFilters(
        owner_id=scope.owner_id,
        key_id=key_id,
        alias=alias,
        status=status_code,
        errors_only=errors_only,
        cache_status=cache_status,
        coalesce_role=coalesce_role,
        tag=tuple(tag.split("=", 1)) if tag else None,
    )
    async with request.app.state.sessionmaker() as session:
        rows = await queries.list_logs(session, filters, limit=limit + 1, before_id=before)
    items = [
        LogOut.model_validate(log_row).model_copy(update={"key_name": name, "key_prefix": prefix})
        for log_row, name, prefix in rows[:limit]
    ]
    return LogPage(items=items, next_cursor=items[-1].id if len(rows) > limit else None)


@router.get("/me")
async def me(request: Request, scope: AdminScope = Depends(admin_scope)) -> Me:
    settings: Settings = request.app.state.settings
    async with request.app.state.sessionmaker() as session:
        keys_list = await queries.list_keys(session, scope.owner_id)
    limits_ = (
        None
        if scope.is_operator
        else UserLimits(
            max_keys=settings.user_max_keys,
            max_rpm=settings.user_max_rpm,
            max_daily_tokens=settings.user_max_daily_tokens,
        )
    )
    return Me(owner_id=scope.owner_id, active_keys=sum(k.revoked_at is None for k in keys_list), limits=limits_)


@router.get("/aliases")
async def aliases(request: Request) -> list[AliasOut]:
    return [
        AliasOut(id=name, chain=[u.model for u in alias.chain], terse=alias.terse)
        for name, alias in request.app.state.aliases.items()
    ]
