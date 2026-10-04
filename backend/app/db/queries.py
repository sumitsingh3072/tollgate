"""Admin queries: keys CRUD, stats (p50/p95), paginated logs. Phases 2 and 4."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey


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
