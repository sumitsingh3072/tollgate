from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

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
def make_client() -> Callable[..., httpx.AsyncClient]:
    """Build an app with fake redis/db on app.state (no lifespan, no network)."""

    def _make(redis_up: bool = True, db_up: bool = True) -> httpx.AsyncClient:
        app: FastAPI = create_app(use_lifespan=False)
        app.state.redis = FakeRedis(redis_up)
        app.state.engine = FakeEngine(db_up)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return _make
