import pytest


@pytest.mark.parametrize(
    ("redis_up", "db_up", "status"),
    [(True, True, "ok"), (False, True, "degraded"), (True, False, "degraded"), (False, False, "degraded")],
)
async def test_health(make_client, redis_up: bool, db_up: bool, status: str) -> None:
    async with make_client(redis_up=redis_up, db_up=db_up) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": status, "redis": redis_up, "db": db_up, "upstream": True, "provider": "gemini"}


async def test_health_flags_missing_gemini_key(redis, engine, http) -> None:
    import httpx

    from app.config import Settings
    from app.main import create_app

    app = create_app(Settings(_env_file=None, environment="test"), use_lifespan=False)
    app.state.redis, app.state.engine, app.state.http = redis, engine, http
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/health")).json()
    assert (body["status"], body["upstream"], body["provider"]) == ("degraded", False, "gemini")
