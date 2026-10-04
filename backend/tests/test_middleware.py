from fastapi import FastAPI


async def test_generates_request_id(make_client) -> None:
    async with make_client() as client:
        resp = await client.get("/health")
    assert len(resp.headers["x-request-id"]) == 32


async def test_propagates_valid_request_id(make_client) -> None:
    async with make_client() as client:
        resp = await client.get("/health", headers={"x-request-id": "abc-123"})
    assert resp.headers["x-request-id"] == "abc-123"


async def test_replaces_unsafe_request_id(make_client) -> None:
    async with make_client() as client:
        resp = await client.get("/health", headers={"x-request-id": "bad id\twith spaces"})
    assert resp.headers["x-request-id"] != "bad id\twith spaces"


async def test_not_found_uses_error_envelope(make_client) -> None:
    async with make_client() as client:
        resp = await client.get("/nope")
    assert resp.status_code == 404
    assert resp.json() == {"error": {"type": "not_found", "message": "Not Found"}}


async def test_unhandled_error_is_masked(make_app) -> None:
    import httpx

    app: FastAPI = make_app()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret detail")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/boom")
    assert resp.status_code == 500
    body = resp.json()["error"]
    assert body["type"] == "server_error"
    assert "secret detail" not in body["message"]
