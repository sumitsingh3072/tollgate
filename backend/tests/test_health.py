import pytest


@pytest.mark.parametrize(
    ("redis_up", "db_up", "status"),
    [(True, True, "ok"), (False, True, "degraded"), (True, False, "degraded"), (False, False, "degraded")],
)
async def test_health(make_client, redis_up: bool, db_up: bool, status: str) -> None:
    async with make_client(redis_up=redis_up, db_up=db_up) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": status, "redis": redis_up, "db": db_up}


def test_normalize_neon_url() -> None:
    from app.config import normalize_database_url

    url = "postgresql://u:p@ep-x.neon.tech/neondb?sslmode=require&channel_binding=require"
    assert normalize_database_url(url) == "postgresql+asyncpg://u:p@ep-x.neon.tech/neondb?ssl=require"
