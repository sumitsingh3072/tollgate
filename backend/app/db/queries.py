"""Admin queries: keys CRUD and paginated logs. Aggregates live in app/db/analytics.py."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
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


# --- logs -----------------------------------------------------------------------------------------


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
        query = query.where(RequestLog.status >= 400)
    result = await session.execute(query)
    return [(row[0], row[1], row[2]) for row in result.all()]
