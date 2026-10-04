"""Control plane: /admin/keys, /admin/stats, /admin/logs. Phases 2 and 4."""

import logging
import uuid
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status

from app.core import keys, limits
from app.db import analytics, queries
from app.deps import require_admin
from app.errors import GatewayError
from app.schemas import (
    ActivityDay,
    AliasOut,
    GroupUsage,
    KeyCreate,
    KeyCreated,
    KeyOut,
    KeyUsage,
    LatencyBin,
    LogOut,
    LogPage,
    PeriodTotals,
    SeriesPoint,
    Stats,
    StatusMix,
)

log = logging.getLogger("tollgate.admin")

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/keys", status_code=status.HTTP_201_CREATED)
async def create_key(body: KeyCreate, request: Request) -> KeyCreated:
    raw = keys.generate_key()
    key_hash = keys.hash_key(raw)
    async with request.app.state.sessionmaker() as session:
        row = await queries.create_key(
            session,
            name=body.name,
            key_hash=key_hash,
            prefix=raw[: keys.DISPLAY_PREFIX_LENGTH],
            rpm=body.rpm,
            daily_token_quota=body.daily_token_quota,
        )
    # Overwrite any negative cache entry so the key works immediately.
    record = keys.KeyRecord(id=row.id, name=row.name, rpm=row.rpm, daily_token_quota=row.daily_token_quota)
    await keys.cache_set(request.app.state.redis, key_hash, record, request.app.state.settings.key_cache_ttl)
    log.info("key created", extra={"key_id": str(row.id), "prefix": row.prefix})
    return KeyCreated(**KeyOut.model_validate(row).model_dump(), key=raw)


@router.get("/keys")
async def list_keys(request: Request) -> list[KeyOut]:
    async with request.app.state.sessionmaker() as session:
        rows = await queries.list_keys(session)
    usage = await limits.tokens_today(request.app.state.redis, [r.id for r in rows if r.revoked_at is None])
    return [KeyOut.model_validate(r).model_copy(update={"tokens_today": usage.get(r.id, 0)}) for r in rows]


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: uuid.UUID, request: Request) -> KeyOut:
    async with request.app.state.sessionmaker() as session:
        row = await queries.revoke_key(session, key_id)
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
async def stats(request: Request, hours: int = Query(default=24, ge=1, le=24 * 30)) -> Stats:
    window = analytics.Window.last(hours)
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


@router.get("/activity")
async def activity(request: Request, days: int = Query(default=365, ge=7, le=366)) -> list[ActivityDay]:
    """Daily totals (UTC) for a contribution-style heatmap; days with no traffic are included as zeros."""
    window = analytics.Window.last(days * 24)
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
) -> LogPage:
    filters = queries.LogFilters(key_id=key_id, alias=alias, status=status_code, errors_only=errors_only)
    async with request.app.state.sessionmaker() as session:
        rows = await queries.list_logs(session, filters, limit=limit + 1, before_id=before)
    items = [
        LogOut.model_validate(log_row).model_copy(update={"key_name": name, "key_prefix": prefix})
        for log_row, name, prefix in rows[:limit]
    ]
    return LogPage(items=items, next_cursor=items[-1].id if len(rows) > limit else None)


@router.get("/aliases")
async def aliases(request: Request) -> list[AliasOut]:
    return [
        AliasOut(id=name, chain=[u.model for u in alias.chain], terse=alias.terse)
        for name, alias in request.app.state.aliases.items()
    ]
