"""Request coalescing: flight semantics and concurrent identical requests through the gateway."""

import asyncio
import json

import httpx
import pytest
import respx
from fastapi import FastAPI

from app.config import Settings
from app.core.coalesce import Coalescer, Flight
from app.errors import GatewayError
from tests.conftest import ADMIN_HEADERS

pytestmark = pytest.mark.respx(assert_all_called=False)

MESSAGES = [{"role": "user", "content": "hi"}]
COMPLETION = {
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "shared"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
}


# --- flight semantics --------------------------------------------------------------------------


async def test_followers_replay_buffered_and_live_chunks() -> None:
    coalescer = Coalescer()
    release = asyncio.Event()

    async def produce(flight: Flight) -> None:
        flight.set_meta("m", False)
        await flight.emit(b"a")
        await release.wait()
        await flight.emit(b"b")

    leader, role1 = coalescer.join("k", produce)
    await leader.wait_ready()
    follower, role2 = coalescer.join("k", produce)  # joins after "a" was produced
    assert (role1, role2, follower is leader) == ("leader", "follower", True)

    async def collect() -> list[bytes]:
        return [c async for c in follower.replay()]

    reader = asyncio.create_task(collect())
    await asyncio.sleep(0)
    release.set()
    assert await reader == [b"a", b"b"]  # late joiner still gets everything
    assert coalescer.stats.followers == 1 and coalescer.in_flight == 0


async def test_error_reaches_every_subscriber() -> None:
    coalescer = Coalescer()
    gate = asyncio.Event()

    async def fail(_: Flight) -> None:
        await gate.wait()
        raise GatewayError(503, "upstream_error", "down")

    a, _ = coalescer.join("k", fail)
    b, _ = coalescer.join("k", fail)
    gate.set()
    for flight in (a, b):
        with pytest.raises(GatewayError):
            await flight.wait_result()


async def test_upstream_cancelled_only_when_nobody_listens() -> None:
    coalescer = Coalescer()
    started = asyncio.Event()

    async def slow(_: Flight) -> str:
        started.set()
        await asyncio.sleep(10)
        return "done"

    flight, _ = coalescer.join("k", slow)
    coalescer.join("k", slow)
    await started.wait()
    coalescer.leave(flight)  # leader's client disconnects
    await asyncio.sleep(0)
    assert not flight.task.cancelled()  # the follower still wants the answer
    coalescer.leave(flight)  # follower gone too
    with pytest.raises(asyncio.CancelledError):
        await flight.task
    assert coalescer.in_flight == 0


async def test_no_key_never_coalesces() -> None:
    coalescer = Coalescer()

    async def produce(_: Flight) -> int:
        return 1

    a, role_a = coalescer.join(None, produce)
    b, role_b = coalescer.join(None, produce)
    assert a is not b and role_a == role_b == "none"
    assert await a.wait_result() == 1


# --- through the gateway -----------------------------------------------------------------------


@pytest.fixture
def slow_gemini(settings: Settings, respx_mock: respx.MockRouter) -> respx.Route:
    async def respond(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        if json.loads(request.content).get("stream"):

            async def sse():
                yield b'data: {"choices":[{"delta":{"content":"sha"},"index":0}]}\n\n'
                await asyncio.sleep(0.01)
                yield b'data: {"choices":[{"delta":{"content":"red"},"index":0,"finish_reason":"stop"}]}\n\n'
                yield b'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}\n\n'
                yield b"data: [DONE]\n\n"

            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse())
        return httpx.Response(200, json=COMPLETION)

    return respx_mock.post(f"{settings.gemini_base_url}/chat/completions").mock(side_effect=respond)


async def test_identical_concurrent_requests_share_one_call(client, auth, app: FastAPI, slow_gemini) -> None:
    payload = {"model": "fast", "messages": MESSAGES, "temperature": 0}

    responses = await asyncio.gather(
        *(client.post("/v1/chat/completions", json=payload, headers=auth) for _ in range(10))
    )

    assert slow_gemini.call_count == 1
    assert all(r.status_code == 200 and r.json() == COMPLETION for r in responses)
    roles = sorted(r.headers["x-tollgate-coalesce"] for r in responses)
    assert roles == ["follower"] * 9 + ["leader"]
    # Popular (>= 2 followers): admitted to the cache immediately, no second sighting needed.
    again = await client.post("/v1/chat/completions", json=payload, headers=auth)
    assert again.headers["x-tollgate-cache"] == "hit"

    await app.state.log_queue.flush()
    logs = (await client.get("/admin/logs?coalesce_role=follower", headers=ADMIN_HEADERS)).json()["items"]
    assert len(logs) == 9 and all(log["in_tokens"] + log["out_tokens"] == 5 for log in logs)  # each pays
    stats = (await client.get("/admin/coalesce/stats", headers=ADMIN_HEADERS)).json()
    assert (stats["leaders"], stats["followers"], stats["calls_saved"]) == (1, 9, 9)
    assert stats["largest_fanout_since_start"] == 10 and stats["share_rate"] == 0.9


async def test_concurrent_streams_fan_out(client, auth, slow_gemini) -> None:
    payload = {"model": "fast", "messages": MESSAGES, "temperature": 0, "stream": True}

    async def read() -> tuple[str, str]:
        async with client.stream("POST", "/v1/chat/completions", json=payload, headers=auth) as resp:
            body = b"".join([c async for c in resp.aiter_bytes()]).decode()
            return resp.headers["x-tollgate-coalesce"], body

    results = await asyncio.gather(*(read() for _ in range(5)))

    assert slow_gemini.call_count == 1
    assert sorted(role for role, _ in results) == ["follower"] * 4 + ["leader"]
    bodies = {body for _, body in results}
    assert len(bodies) == 1 and '"red"' in bodies.pop()


async def test_different_keys_never_coalesce_in_private_scope(client, auth, create_key, slow_gemini) -> None:
    other = await create_key(rpm=100)
    payload = {"model": "fast", "messages": MESSAGES, "temperature": 0}

    await asyncio.gather(
        client.post("/v1/chat/completions", json=payload, headers=auth),
        client.post("/v1/chat/completions", json=payload, headers={"Authorization": f"Bearer {other['key']}"}),
    )

    assert slow_gemini.call_count == 2


async def test_nondeterministic_requests_never_coalesce(client, auth, slow_gemini) -> None:
    payload = {"model": "fast", "messages": MESSAGES, "temperature": 0.8}
    await asyncio.gather(*(client.post("/v1/chat/completions", json=payload, headers=auth) for _ in range(3)))
    assert slow_gemini.call_count == 3


async def test_coalescing_can_be_disabled(make_app, settings, slow_gemini, create_key) -> None:
    settings.coalescing_enabled = False
    key = await create_key(rpm=100)
    transport = httpx.ASGITransport(app=make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        payload = {"model": "fast", "messages": MESSAGES, "temperature": 0}
        headers = {"Authorization": f"Bearer {key['key']}"}
        await asyncio.gather(*(c.post("/v1/chat/completions", json=payload, headers=headers) for _ in range(3)))
    assert slow_gemini.call_count == 3
