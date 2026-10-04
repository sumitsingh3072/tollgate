"""App factory and lifespan (shared httpx client, redis, db engine)."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import admin, v1
from app.config import DEFAULT_ADMIN_TOKEN, Settings, build_aliases, get_settings, upstream_models
from app.core import tasks
from app.core.coalesce import Coalescer
from app.core.fair_queue import FairQueue
from app.core.fallback import CircuitBreakers
from app.db.session import create_engine, create_sessionmaker, init_db
from app.deps import require_admin
from app.errors import install_error_handlers
from app.logging_queue import LogQueue
from app.logging_setup import configure_logging
from app.middleware import RequestContextMiddleware
from app.telemetry import metrics

log = logging.getLogger("tollgate")

HEALTH_CHECK_TIMEOUT = 3.0  # Neon can take ~1-2s to wake from scale-to-zero
# Exposed to browsers (the dashboard Playground reads them).
TOLLGATE_HEADERS = [
    "x-tollgate-model",
    "x-tollgate-cache",
    "x-tollgate-fallback",
    "x-request-id",
    "x-tollgate-coalesce",
    "x-tollgate-queue-wait-ms",
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "retry-after",
]


def _check_admin_token(settings: Settings) -> None:
    if settings.admin_token.get_secret_value() != DEFAULT_ADMIN_TOKEN:
        return
    if settings.environment == "production":
        raise RuntimeError("ADMIN_TOKEN is the public default; set ADMIN_TOKEN or ADMIN_TOKEN_FILE")
    log.warning("ADMIN_TOKEN is the default value; set a strong token before exposing the gateway")


def _warn_on_insecure_config(settings: Settings) -> None:
    _check_admin_token(settings)
    if settings.upstream_provider == "gemini" and not settings.gemini_api_key.get_secret_value():
        log.warning("GEMINI_API_KEY is not set; upstream calls will fail with 401")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    _warn_on_insecure_config(settings)

    app.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.upstream_timeout, connect=settings.upstream_connect_timeout),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.redis_cache = (
        aioredis.from_url(settings.redis_cache_url, decode_responses=True)
        if settings.redis_cache_url
        else app.state.redis
    )
    app.state.engine = create_engine(settings.database_url)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    try:
        await init_db(app.state.engine)
    except Exception:
        # Keep serving; /health reports db=false until the DB is reachable.
        log.exception("database init failed; continuing without schema check")

    app.state.log_queue = LogQueue(app.state.sessionmaker, settings.log_flush_interval)
    app.state.log_queue.start()

    log.info(
        "gateway started",
        extra={
            "env": settings.environment,
            "provider": settings.upstream_provider,
            "aliases": ",".join(app.state.aliases),
        },
    )
    try:
        yield
    finally:
        await app.state.coalescer.shutdown()
        await tasks.drain()
        await app.state.log_queue.stop()  # final flush before the engine closes
        await app.state.http.aclose()
        if app.state.redis_cache is not app.state.redis:
            await app.state.redis_cache.aclose()
        await app.state.redis.aclose()
        await app.state.engine.dispose()
        log.info("gateway stopped")


def create_app(settings: Settings | None = None, *, use_lifespan: bool = True) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title="Tollgate Lite",
        version="0.1.0",
        lifespan=lifespan if use_lifespan else None,
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.aliases = build_aliases(settings)
    app.state.breakers = CircuitBreakers(settings.breaker_failure_threshold, settings.breaker_open_seconds)
    app.state.coalescer = Coalescer()
    app.state.fair_queue = FairQueue(
        mode=settings.fair_queue_mode,
        parallel=settings.upstream_max_parallel,
        max_queue=settings.fair_max_queue_per_key,
        max_wait_s=settings.fair_max_wait_s,
        output_weight=settings.fair_output_weight,
    )

    # Order matters: the last-added middleware is outermost, so request ids wrap CORS too.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
        expose_headers=TOLLGATE_HEADERS,
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    app.include_router(v1.router)
    app.include_router(admin.router)

    @app.get("/metrics", tags=["ops"], dependencies=[Depends(require_admin)], include_in_schema=False)
    async def prometheus_metrics() -> Response:
        """Prometheus exposition format. Scrape with `authorization: {credentials: <ADMIN_TOKEN>}`."""
        content, media_type = metrics.render()
        return Response(content, media_type=media_type)

    @app.get("/health/live", tags=["ops"])
    async def live() -> dict[str, str]:
        """Liveness for container orchestrators: the process is up. No dependency checks, so a slow
        database or a missing API key never gets a healthy gateway restarted."""
        return {"status": "ok"}

    @app.get("/health", tags=["ops"])
    async def health(request: Request) -> dict[str, object]:
        redis_ok, db_ok, upstream = await asyncio.gather(
            _check_redis(request.app), _check_db(request.app), _check_upstream(request.app)
        )
        # upstream: is the model provider usable? Gemini: an API key is configured (not probed: cost,
        # rate limits). Ollama: every configured model is downloaded.
        return {
            "status": "ok" if redis_ok and db_ok and upstream else "degraded",
            "redis": redis_ok,
            "db": db_ok,
            "upstream": upstream,
            "provider": request.app.state.settings.upstream_provider,
        }

    return app


async def _check_redis(app: FastAPI) -> bool:
    try:
        return bool(await asyncio.wait_for(app.state.redis.ping(), HEALTH_CHECK_TIMEOUT))
    except Exception as exc:
        log.warning("redis health check failed", extra={"error": repr(exc)})
        return False


async def _check_upstream(app: FastAPI) -> bool:
    settings: Settings = app.state.settings
    if settings.upstream_provider == "gemini":
        return bool(settings.gemini_api_key.get_secret_value())
    try:
        resp = await app.state.http.get(f"{settings.ollama_base_url}/models", timeout=HEALTH_CHECK_TIMEOUT)
        resp.raise_for_status()
        available = {m["id"] for m in resp.json().get("data", [])}
    except Exception as exc:
        log.warning("ollama health check failed", extra={"error": repr(exc)})
        return False
    wanted = {u.model for u in upstream_models(settings)}
    missing = wanted - available
    if missing:
        log.warning("ollama models not pulled yet", extra={"missing": ",".join(sorted(missing))})
    return not missing


async def _check_db(app: FastAPI) -> bool:
    async def ping() -> None:
        async with app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(ping(), HEALTH_CHECK_TIMEOUT)
        return True
    except Exception as exc:
        log.warning("db health check failed", extra={"error": repr(exc)})
        return False


app = create_app()
