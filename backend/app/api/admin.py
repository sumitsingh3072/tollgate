"""Control plane: /admin/keys, /admin/stats, /admin/logs. Phases 2 and 4."""

import logging
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request, status

from app.core import keys, limits
from app.db import queries
from app.deps import require_admin
from app.errors import GatewayError
from app.schemas import KeyCreate, KeyCreated, KeyOut, KeyUsage, LogOut, LogPage, ModelUsage, Stats

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


@router.get("/stats")
async def stats(request: Request, hours: int = Query(default=24, ge=1, le=24 * 30)) -> Stats:
    since = datetime.now(UTC) - timedelta(hours=hours)
    async with request.app.state.sessionmaker() as session:
        totals = await queries.totals(session, since)
        by_key = await queries.usage_by_key(session, since)
        by_model = await queries.usage_by_model(session, since)
    return Stats(
        window_hours=hours,
        error_rate=_rate(totals.errors, totals.requests),
        cache_hit_rate=_rate(totals.cache_hits, totals.requests),
        by_key=[KeyUsage(**asdict(row)) for row in by_key],
        by_model=[ModelUsage(**asdict(row)) for row in by_model],
        **asdict(totals),
    )


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
