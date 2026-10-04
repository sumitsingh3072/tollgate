"""Async engine, session factory, and create_all on startup."""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base


def create_engine(database_url: str) -> AsyncEngine:
    # pool_pre_ping: Neon closes idle connections (scale-to-zero)
    return create_async_engine(database_url, pool_size=5, max_overflow=5, pool_pre_ping=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
