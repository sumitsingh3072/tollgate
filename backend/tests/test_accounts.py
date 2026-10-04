import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from app.logging_queue import LogEvent
from tests.conftest import ADMIN_HEADERS


def as_user(user_id: str) -> dict[str, str]:
    return {**ADMIN_HEADERS, "X-Tollgate-User": user_id}


ALICE, BOB = as_user("user_alice"), as_user("user_bob")


async def create(client: httpx.AsyncClient, headers: dict[str, str], **body) -> httpx.Response:
    payload = {"name": "k", "rpm": 10, "daily_token_quota": 1000, **body}
    return await client.post("/admin/keys", json=payload, headers=headers)


async def test_users_only_see_their_own_keys(client: httpx.AsyncClient) -> None:
    a = (await create(client, ALICE, name="alice-key")).json()
    b = (await create(client, BOB, name="bob-key")).json()

    alice_keys = (await client.get("/admin/keys", headers=ALICE)).json()
    operator_keys = (await client.get("/admin/keys", headers=ADMIN_HEADERS)).json()

    assert [k["id"] for k in alice_keys] == [a["id"]]
    assert {k["id"] for k in operator_keys} == {a["id"], b["id"]}  # operator view sees everything


async def test_users_cannot_revoke_other_users_keys(client: httpx.AsyncClient) -> None:
    b = (await create(client, BOB)).json()

    stolen = await client.delete(f"/admin/keys/{b['id']}", headers=ALICE)

    assert stolen.status_code == 404  # indistinguishable from a missing key
    still_active = (await client.get("/admin/keys", headers=BOB)).json()[0]
    assert still_active["revoked_at"] is None
    assert (await client.delete(f"/admin/keys/{b['id']}", headers=BOB)).status_code == 200


async def test_stats_activity_and_logs_are_scoped(client: httpx.AsyncClient, app: FastAPI) -> None:
    a = (await create(client, ALICE)).json()
    b = (await create(client, BOB)).json()
    for key_id, count in ((a["id"], 2), (b["id"], 3)):
        for _ in range(count):
            app.state.log_queue.enqueue(
                LogEvent(
                    ts=datetime.now(UTC),
                    key_id=uuid.UUID(key_id),
                    alias="fast",
                    model_used="m",
                    in_tokens=1,
                    out_tokens=1,
                    latency_ms=10,
                    status=200,
                    cache_hit=False,
                    fallback_used=False,
                )
            )
    await app.state.log_queue.flush()

    assert (await client.get("/admin/stats", headers=ALICE)).json()["requests"] == 2
    assert (await client.get("/admin/stats", headers=BOB)).json()["requests"] == 3
    assert (await client.get("/admin/stats", headers=ADMIN_HEADERS)).json()["requests"] == 5
    assert len((await client.get("/admin/logs", headers=ALICE)).json()["items"]) == 2
    assert sum(d["requests"] for d in (await client.get("/admin/activity?days=7", headers=BOB)).json()) == 3
    # Filtering by someone else's key id returns nothing rather than their logs.
    assert (await client.get(f"/admin/logs?key_id={b['id']}", headers=ALICE)).json()["items"] == []


async def test_user_caps(client: httpx.AsyncClient, settings) -> None:
    too_fast = await create(client, ALICE, rpm=settings.user_max_rpm + 1)
    too_big = await create(client, ALICE, daily_token_quota=settings.user_max_daily_tokens + 1)
    assert too_fast.status_code == too_big.status_code == 422

    for _ in range(settings.user_max_keys):
        assert (await create(client, ALICE)).status_code == 201
    over = await create(client, ALICE)
    assert over.status_code == 403 and over.json()["error"]["type"] == "key_limit"

    # Revoking frees a slot; the operator is never capped.
    first = (await client.get("/admin/keys", headers=ALICE)).json()[0]
    await client.delete(f"/admin/keys/{first['id']}", headers=ALICE)
    assert (await create(client, ALICE)).status_code == 201
    assert (await create(client, ADMIN_HEADERS, rpm=10_000, daily_token_quota=10_000_000)).status_code == 201


@pytest.mark.parametrize("user", ["", "user with spaces", "x" * 129, "user;drop"])
async def test_malformed_user_header_rejected(client: httpx.AsyncClient, user: str) -> None:
    resp = await client.get("/admin/keys", headers=as_user(user))
    assert resp.status_code == 400


async def test_user_header_needs_admin_token(client: httpx.AsyncClient) -> None:
    resp = await client.get("/admin/keys", headers={"X-Tollgate-User": "user_alice"})
    assert resp.status_code == 401


async def test_user_keys_work_on_v1(client: httpx.AsyncClient) -> None:
    key = (await create(client, ALICE)).json()["key"]
    assert (await client.get("/v1/models", headers={"Authorization": f"Bearer {key}"})).status_code == 200


async def test_me_reports_caps_for_users_only(client: httpx.AsyncClient, settings) -> None:
    await create(client, ALICE)
    me = (await client.get("/admin/me", headers=ALICE)).json()
    assert me == {
        "owner_id": "user_alice",
        "active_keys": 1,
        "limits": {
            "max_keys": settings.user_max_keys,
            "max_rpm": settings.user_max_rpm,
            "max_daily_tokens": settings.user_max_daily_tokens,
        },
    }
    assert (await client.get("/admin/me", headers=ADMIN_HEADERS)).json()["limits"] is None
