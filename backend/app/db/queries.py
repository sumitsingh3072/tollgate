"""Admin queries: keys CRUD, stats (p50/p95), paginated logs. Phases 2 and 4."""

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey, RequestLog


async def create_key(
    session: AsyncSession, *, name: str, key_hash: str, prefix: str, rpm: int, daily_token_quota: int
) -> ApiKey:
    key = ApiKey(name=name, key_hash=key_hash, prefix=prefix, rpm=rpm, daily_token_quota=daily_token_quota)
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return key


async def list_keys(session: AsyncSession) -> list[ApiKey]:
    result = await session.scalars(select(ApiKey).order_by(ApiKey.created_at.desc(), ApiKey.id))
    return list(result)


async def get_active_key_by_hash(session: AsyncSession, key_hash: str) -> ApiKey | None:
    return await session.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None)))


async def revoke_key(session: AsyncSession, key_id: uuid.UUID) -> ApiKey | None:
    """Idempotent: revoking an already-revoked key keeps the original revoked_at."""
    key = await session.get(ApiKey, key_id)
    if key is None:
        return None
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        await session.commit()
    return key


# --- analytics ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Totals:
    requests: int
    errors: int
    cache_hits: int
    fallbacks: int
    in_tokens: int
    out_tokens: int
    p50_latency_ms: float | None
    p95_latency_ms: float | None


@dataclass(frozen=True)
class KeyUsageRow:
    key_id: uuid.UUID | None
    name: str | None
    prefix: str | None
    requests: int
    tokens: int
    errors: int


@dataclass(frozen=True)
class ModelUsageRow:
    model: str | None
    requests: int
    tokens: int


_ERRORS = RequestLog.status >= 400
_TOKENS = RequestLog.in_tokens + RequestLog.out_tokens


def _percentile(sorted_values: list[int], q: float) -> float | None:
    """Linear interpolation, identical to Postgres percentile_cont."""
    if not sorted_values:
        return None
    pos = (len(sorted_values) - 1) * q
    lower, upper = math.floor(pos), math.ceil(pos)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (pos - lower)


async def _latency_percentiles(session: AsyncSession, since: datetime) -> tuple[float | None, float | None]:
    window = RequestLog.ts >= since
    if session.bind.dialect.name == "postgresql":
        latency = RequestLog.latency_ms.asc()
        row = (
            await session.execute(
                select(
                    func.percentile_cont(0.5).within_group(latency),
                    func.percentile_cont(0.95).within_group(latency),
                ).where(window)
            )
        ).one()
        return row[0], row[1]
    # Other dialects (SQLite in tests) lack percentile_cont; compute the same thing in Python.
    values = sorted((await session.scalars(select(RequestLog.latency_ms).where(window))).all())
    return _percentile(values, 0.5), _percentile(values, 0.95)


async def totals(session: AsyncSession, since: datetime) -> Totals:
    row = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(_ERRORS),
                func.count().filter(RequestLog.cache_hit.is_(True)),
                func.count().filter(RequestLog.fallback_used.is_(True)),
                func.coalesce(func.sum(RequestLog.in_tokens), 0),
                func.coalesce(func.sum(RequestLog.out_tokens), 0),
            ).where(RequestLog.ts >= since)
        )
    ).one()
    p50, p95 = await _latency_percentiles(session, since)
    return Totals(*(int(v) for v in row), p50_latency_ms=p50, p95_latency_ms=p95)


async def usage_by_key(session: AsyncSession, since: datetime) -> list[KeyUsageRow]:
    tokens = func.coalesce(func.sum(_TOKENS), 0)
    result = await session.execute(
        select(RequestLog.key_id, ApiKey.name, ApiKey.prefix, func.count(), tokens, func.count().filter(_ERRORS))
        .outerjoin(ApiKey, ApiKey.id == RequestLog.key_id)
        .where(RequestLog.ts >= since)
        .group_by(RequestLog.key_id, ApiKey.name, ApiKey.prefix)
        .order_by(tokens.desc())
    )
    return [KeyUsageRow(*row) for row in result.all()]


async def usage_by_model(session: AsyncSession, since: datetime) -> list[ModelUsageRow]:
    tokens = func.coalesce(func.sum(_TOKENS), 0)
    result = await session.execute(
        select(RequestLog.model_used, func.count(), tokens)
        .where(RequestLog.ts >= since)
        .group_by(RequestLog.model_used)
        .order_by(func.count().desc())
    )
    return [ModelUsageRow(*row) for row in result.all()]


@dataclass(frozen=True)
class LogFilters:
    key_id: uuid.UUID | None = None
    alias: str | None = None
    status: int | None = None
    errors_only: bool = False


async def list_logs(
    session: AsyncSession, filters: LogFilters, *, limit: int, before_id: int | None = None
) -> list[tuple[RequestLog, str | None, str | None]]:
    """Newest first, keyset-paginated on id (stable and index-friendly, unlike OFFSET)."""
    query = (
        select(RequestLog, ApiKey.name, ApiKey.prefix)
        .outerjoin(ApiKey, ApiKey.id == RequestLog.key_id)
        .order_by(RequestLog.id.desc())
        .limit(limit)
    )
    if before_id is not None:
        query = query.where(RequestLog.id < before_id)
    if filters.key_id is not None:
        query = query.where(RequestLog.key_id == filters.key_id)
    if filters.alias is not None:
        query = query.where(RequestLog.alias == filters.alias)
    if filters.status is not None:
        query = query.where(RequestLog.status == filters.status)
    if filters.errors_only:
        query = query.where(_ERRORS)
    result = await session.execute(query)
    return [(row[0], row[1], row[2]) for row in result.all()]
