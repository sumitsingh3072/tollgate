from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.session import create_sessionmaker, init_db
from app.logging_queue import LogQueue
from app.main import create_app

ADMIN_HEADERS = {"Authorization": "Bearer test-admin"}


class DownRedis:
    """Every command fails like an unreachable Redis."""

    def __getattr__(self, name: str) -> Callable[..., Awaitable[Any]]:
        async def _fail(*_: Any, **__: Any) -> Any:
            raise RedisConnectionError("redis down")

        return _fail


class DownEngine:
    @asynccontextmanager
    async def connect(self) -> AsyncIterator[None]:
        raise OSError("db down")
        yield


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: tests never read a developer's real .env
    # Most suites exercise the Gemini path (keys, extra_body); test_local.py covers Ollama.
    return Settings(
        _env_file=None,
        environment="test",
        upstream_provider="gemini",
        gemini_api_key="test-key",
        admin_token="test-admin",
    )


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    """The shared upstream client; tests intercept it with respx."""
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
async def redis() -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    # One shared in-memory SQLite connection stands in for Postgres.
    eng = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    await init_db(eng)
    yield eng
    await eng.dispose()


@pytest.fixture
def make_app(settings: Settings, http: httpx.AsyncClient, redis: FakeAsyncRedis, engine: AsyncEngine):
    """Build an app on fake redis + SQLite (no lifespan, no real network)."""

    def _make(redis_up: bool = True, db_up: bool = True) -> FastAPI:
        app = create_app(settings, use_lifespan=False)
        app.state.redis = redis if redis_up else DownRedis()
        app.state.engine = engine if db_up else DownEngine()
        app.state.sessionmaker = create_sessionmaker(engine)
        app.state.http = http
        # Not started: tests flush explicitly instead of waiting for the timer.
        app.state.log_queue = LogQueue(app.state.sessionmaker, settings.log_flush_interval)
        return app

    return _make


@pytest.fixture
def make_client(make_app: Callable[..., FastAPI]) -> Callable[..., httpx.AsyncClient]:
    def _make(**kwargs: bool) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=make_app(**kwargs), raise_app_exceptions=False)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    return _make


@pytest.fixture
def app(make_app: Callable[..., FastAPI]) -> FastAPI:
    return make_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def create_key(client: httpx.AsyncClient) -> Callable[..., Awaitable[dict[str, Any]]]:
    async def _create(**overrides: Any) -> dict[str, Any]:
        resp = await client.post("/admin/keys", json={"name": "test", **overrides}, headers=ADMIN_HEADERS)
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _create


@pytest.fixture
async def auth(create_key: Callable[..., Awaitable[dict[str, Any]]]) -> dict[str, str]:
    """Authorization header for a freshly created key with generous limits."""
    key = await create_key(rpm=1000, daily_token_quota=1_000_000)
    return {"Authorization": f"Bearer {key['key']}"}
