"""App factory and lifespan (shared httpx client, redis, db engine)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import admin, v1
from app.config import get_settings
from app.db.session import create_engine, create_sessionmaker, init_db

log = logging.getLogger("tollgate")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.upstream_timeout, connect=5.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.engine = create_engine(settings.database_url)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    try:
        await init_db(app.state.engine)
    except Exception:
        # Keep serving; /health reports db=false until the DB is reachable.
        log.exception("create_all failed")
    try:
        yield
    finally:
        await app.state.http.aclose()
        await app.state.redis.aclose()
        await app.state.engine.dispose()


def create_app(*, use_lifespan: bool = True) -> FastAPI:
    app = FastAPI(title="Tollgate Lite", lifespan=lifespan if use_lifespan else None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-tollgate-model", "x-tollgate-cache", "x-tollgate-fallback"],
    )
    app.include_router(v1.router)
    app.include_router(admin.router)

    @app.get("/health")
    async def health(request: Request) -> dict[str, object]:
        redis_ok = await _check_redis(request.app)
        db_ok = await _check_db(request.app)
        return {"status": "ok" if redis_ok and db_ok else "degraded", "redis": redis_ok, "db": db_ok}

    return app


async def _check_redis(app: FastAPI) -> bool:
    try:
        return bool(await app.state.redis.ping())
    except Exception:
        return False


async def _check_db(app: FastAPI) -> bool:
    try:
        async with app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


app = create_app()
