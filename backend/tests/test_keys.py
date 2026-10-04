import httpx
import pytest
from fakeredis import FakeAsyncRedis

from app.core.keys import KEY_PREFIX, hash_key
from tests.conftest import ADMIN_HEADERS


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic test-admin"}])
async def test_admin_requires_token(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    resp = await client.get("/admin/keys", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"]["type"] == "authentication_error"


async def test_create_key_returns_full_key_once(client: httpx.AsyncClient, redis: FakeAsyncRedis, create_key) -> None:
    created = await create_key(name="ci", rpm=5, daily_token_quota=500)

    raw = created["key"]
    assert raw.startswith(KEY_PREFIX) and len(raw) == len(KEY_PREFIX) + 32
    assert created["prefix"] == raw[: len(KEY_PREFIX) + 4]
    assert (created["name"], created["rpm"], created["daily_token_quota"]) == ("ci", 5, 500)
    assert await redis.get(f"key:{hash_key(raw)}") is not None  # warm cache: usable immediately

    listed = (await client.get("/admin/keys", headers=ADMIN_HEADERS)).json()
    assert [k["id"] for k in listed] == [created["id"]]
    assert "key" not in listed[0] and "key_hash" not in listed[0]


async def test_keys_are_unique(create_key) -> None:
    a, b = await create_key(), await create_key()
    assert a["key"] != b["key"]


@pytest.mark.parametrize(
    "body", [{"name": ""}, {"name": "x", "rpm": 0}, {"name": "x", "daily_token_quota": -1}, {"name": "x", "bad": 1}]
)
async def test_create_key_validation(client: httpx.AsyncClient, body: dict) -> None:
    resp = await client.post("/admin/keys", json=body, headers=ADMIN_HEADERS)
    assert resp.status_code == 422


async def test_v1_requires_valid_key(client: httpx.AsyncClient) -> None:
    missing = await client.get("/v1/models")
    malformed = await client.get("/v1/models", headers={"Authorization": "Bearer sk-openai-style"})
    unknown = await client.get("/v1/models", headers={"Authorization": f"Bearer {KEY_PREFIX}{'x' * 32}"})

    assert [r.status_code for r in (missing, malformed, unknown)] == [401, 401, 401]
    assert "Missing API key" in missing.json()["error"]["message"]


async def test_unknown_key_is_negatively_cached(client: httpx.AsyncClient, redis: FakeAsyncRedis) -> None:
    raw = f"{KEY_PREFIX}{'y' * 32}"
    await client.get("/v1/models", headers={"Authorization": f"Bearer {raw}"})
    assert await redis.get(f"key:{hash_key(raw)}") == "-"


async def test_cache_miss_falls_back_to_db(client: httpx.AsyncClient, redis: FakeAsyncRedis, create_key) -> None:
    created = await create_key()
    await redis.flushall()

    resp = await client.get("/v1/models", headers={"Authorization": f"Bearer {created['key']}"})

    assert resp.status_code == 200
    assert await redis.get(f"key:{hash_key(created['key'])}") is not None


async def test_revoke_blocks_key_immediately(client: httpx.AsyncClient, create_key) -> None:
    created = await create_key()
    auth = {"Authorization": f"Bearer {created['key']}"}
    assert (await client.get("/v1/models", headers=auth)).status_code == 200

    revoked = await client.delete(f"/admin/keys/{created['id']}", headers=ADMIN_HEADERS)

    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None
    assert (await client.get("/v1/models", headers=auth)).status_code == 401
    again = await client.delete(f"/admin/keys/{created['id']}", headers=ADMIN_HEADERS)
    assert again.json()["revoked_at"] == revoked.json()["revoked_at"]  # idempotent


async def test_revoke_unknown_key_is_404(client: httpx.AsyncClient) -> None:
    resp = await client.delete("/admin/keys/00000000-0000-0000-0000-000000000000", headers=ADMIN_HEADERS)
    assert resp.status_code == 404
