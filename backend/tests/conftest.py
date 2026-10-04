from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app


class FakeRedis:
    def __init__(self, up: bool = True) -> None:
        self.up = up

    async def ping(self) -> bool:
        if not self.up:
            raise ConnectionError("redis down")
        return True


class FakeConn:
    async def execute(self, _stmt: object) -> None:
        return None


class FakeEngine:
    def __init__(self, up: bool = True) -> None:
        self.up = up

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[FakeConn]:
        if not self.up:
            raise OSError("db down")
        yield FakeConn()


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: tests never read a developer's real .env
    return Settings(_env_file=None, environment="test", gemini_api_key="test-key", admin_token="test-admin")


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    """The shared upstream client; tests intercept it with respx."""
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def make_app(settings: Settings, http: httpx.AsyncClient) -> Callable[..., FastAPI]:
    """Build an app with fake redis/db on app.state (no lifespan, no real network)."""

    def _make(redis_up: bool = True, db_up: bool = True) -> FastAPI:
        app = create_app(settings, use_lifespan=False)
        app.state.redis = FakeRedis(redis_up)
        app.state.engine = FakeEngine(db_up)
        app.state.http = http
        return app

    return _make


@pytest.fixture
def make_client(make_app: Callable[..., FastAPI]) -> Callable[..., httpx.AsyncClient]:
    def _make(**kwargs: bool) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=make_app(**kwargs), raise_app_exceptions=False)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    return _make
