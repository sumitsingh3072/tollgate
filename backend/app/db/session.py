"""Async engine, session factory, and create_all + additive migrations on startup."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base


def create_engine(database_url: str) -> AsyncEngine:
    # pool_pre_ping: Neon closes idle connections (scale-to-zero)
    return create_async_engine(database_url, pool_size=5, max_overflow=5, pool_pre_ping=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# Additive, idempotent schema changes for databases created before a column existed
# (create_all never alters existing tables, and the project deliberately has no Alembic).
_POSTGRES_MIGRATIONS = (
    "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS owner_id TEXT",
    "CREATE INDEX IF NOT EXISTS ix_api_keys_owner_id ON api_keys (owner_id)",
    "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS cache_status TEXT",
    "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS cache_scope TEXT",
    "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS coalesce_role TEXT",
    "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS queue_wait_ms INTEGER",
    "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS ttft_ms INTEGER",
    "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS tags JSONB",
)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name == "postgresql":
            for statement in _POSTGRES_MIGRATIONS:
                await conn.execute(text(statement))
