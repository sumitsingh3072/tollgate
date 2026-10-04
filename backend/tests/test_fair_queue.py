"""Fair queuing (VTC): ordering, counter lift, backpressure, cancellation, and the gateway path."""

import asyncio
import json

import httpx
import pytest
import respx

from app.config import Settings
from app.core.fair_queue import FairQueue, FairScheduler, VirtualCounters
from app.errors import GatewayError

pytestmark = pytest.mark.respx(assert_all_called=False)


def scheduler(parallel: int = 1, *, mode: str = "fair", max_queue: int = 20, max_wait_s: float = 5) -> FairScheduler:
    return FairScheduler("m", parallel, VirtualCounters(), mode=mode, max_queue=max_queue, max_wait_s=max_wait_s)


async def run_order(s: FairScheduler, plan: list[str]) -> list[str]:
    """Occupy the slot, queue `plan` (key ids in arrival order), then record dispatch order."""
    holder = await s.acquire("holder", "h")
    order: list[str] = []

    async def job(key: str) -> None:
        ticket = await s.acquire(key, key)
        order.append(key)
        s.counters.charge(key, input_tokens=100)  # every request costs the same
        s.release(ticket)

    tasks = []
    for key in plan:
        tasks.append(asyncio.create_task(job(key)))
        await asyncio.sleep(0)  # deterministic arrival order
    s.release(holder)
    await asyncio.gather(*tasks)
    return order


async def test_light_key_is_not_stuck_behind_heavy_backlog() -> None:
    plan = ["heavy"] * 5 + ["light"]
    fair = await run_order(scheduler(), plan)
    fifo = await run_order(scheduler(mode="fifo"), plan)
    assert fifo.index("light") == 5  # first-come first-served: waits behind everything
    assert fair.index("light") <= 1  # VTC: lowest counter goes next


async def test_round_robin_between_equal_keys() -> None:
    order = await run_order(scheduler(), ["a", "a", "a", "b", "b", "b"])
    assert order == ["a", "b", "a", "b", "a", "b"]


def test_counter_lift_for_returning_key() -> None:
    counters = VirtualCounters()
    counters.activate("busy")
    counters.charge("busy", input_tokens=1_000)
    counters.activate("returning")  # was idle with 0 served
    assert counters.value("returning") == 1_000  # cannot bank idle time
    counters.deactivate("busy")
    counters.deactivate("returning")
    assert counters.active == set()


def test_output_tokens_weigh_double() -> None:
    counters = VirtualCounters(output_weight=2.0)
    counters.charge("k", input_tokens=10, output_tokens=5)
    assert counters.value("k") == 20


async def test_queue_full_is_429() -> None:
    s = scheduler(max_queue=2)
    holder = await s.acquire("x", "x")
    waiting = [asyncio.create_task(s.acquire("k", "k")) for _ in range(2)]
    await asyncio.sleep(0)
    with pytest.raises(GatewayError) as err:
        await s.acquire("k", "k")
    assert err.value.status_code == 429 and err.value.type == "queue_full"
    assert err.value.headers["Retry-After"] == "1"
    s.release(holder)
    for t in waiting:
        s.release(await t)


async def test_max_wait_is_429_and_frees_place() -> None:
    s = scheduler(max_wait_s=0.05)
    holder = await s.acquire("x", "x")
    with pytest.raises(GatewayError) as err:
        await s.acquire("k", "k")
    assert err.value.type == "queue_timeout" and "Retry-After" in err.value.headers
    assert s.depth_by_key() == {}
    s.release(holder)
    assert s.running == 0


async def test_cancelled_waiter_leaves_queue() -> None:
    s = scheduler()
    holder = await s.acquire("x", "x")
    waiter = asyncio.create_task(s.acquire("k", "k"))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert s.depth_by_key() == {}
    s.release(holder)
    assert s.running == 0 and s.counters.active == set()


async def test_off_mode_never_queues() -> None:
    q = FairQueue(mode="off", parallel=1, max_queue=1, max_wait_s=1, output_weight=2)
    async with q.slot("m", "k", "k") as a, q.slot("m", "k", "k") as b:
        assert a is None and b is None


# --- through the gateway ------------------------------------------------------------------------


@pytest.fixture
def gpu(settings: Settings, respx_mock: respx.MockRouter) -> list[str]:
    """A one-slot 'model': each request takes 20 ms; records which prompt was served when."""
    served: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["messages"][-1]["content"]
        served.append(prompt)
        await asyncio.sleep(0.02)
        return httpx.Response(
            200,
            json={
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 50, "total_tokens": 100},
            },
        )

    respx_mock.post(f"{settings.gemini_base_url}/chat/completions").mock(side_effect=respond)
    return served


async def test_gateway_serves_light_key_before_heavy_backlog(make_app, settings, create_key, gpu) -> None:
    settings.upstream_max_parallel = 1
    heavy, light = await create_key(rpm=1000), await create_key(rpm=1000)
    transport = httpx.ASGITransport(app=make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:

        async def ask(key: dict, prompt: str) -> httpx.Response:
            body = {"model": "fast", "messages": [{"role": "user", "content": prompt}]}
            return await c.post("/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {key['key']}"})

        heavy_jobs = [asyncio.create_task(ask(heavy, f"heavy-{i}")) for i in range(6)]
        await asyncio.sleep(0.005)
        light_resp = await ask(light, "light")
        await asyncio.gather(*heavy_jobs)

    assert gpu.index("light") <= 2  # not 7th
    assert int(light_resp.headers["x-tollgate-queue-wait-ms"]) >= 0


async def test_gateway_queue_full_returns_429(make_app, settings, create_key, gpu) -> None:
    settings.upstream_max_parallel = 1
    settings.fair_max_queue_per_key = 2
    key = await create_key(rpm=1000)
    transport = httpx.ASGITransport(app=make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        body = lambda i: {"model": "fast", "messages": [{"role": "user", "content": f"p{i}"}]}  # noqa: E731
        results = await asyncio.gather(
            *(
                c.post("/v1/chat/completions", json=body(i), headers={"Authorization": f"Bearer {key['key']}"})
                for i in range(5)
            )
        )
    codes = sorted(r.status_code for r in results)
    assert codes.count(429) == 2 and codes.count(200) == 3  # 1 running + 2 queued
    rejected = next(r for r in results if r.status_code == 429)
    assert rejected.json()["error"]["type"] == "queue_full"


def test_jain_index() -> None:
    from app.db.analytics import jain_index

    assert jain_index([10, 10, 10]) == 1.0
    assert jain_index([30, 0, 0]) == 1.0  # idle keys don't count
    assert abs(jain_index([90, 10]) - 0.6098) < 1e-3
    assert jain_index([]) is None


async def test_fairness_endpoint(make_app, settings, create_key, gpu) -> None:
    from tests.conftest import ADMIN_HEADERS

    settings.upstream_max_parallel = 1
    a, b = await create_key(rpm=1000, name="a"), await create_key(rpm=1000, name="b")
    app = make_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        for key, n in ((a, 3), (b, 1)):
            for i in range(n):
                body = {"model": "fast", "messages": [{"role": "user", "content": f"{key['name']}{i}"}]}
                await c.post("/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {key['key']}"})
        await app.state.log_queue.flush()
        data = (await c.get("/admin/fairness", headers=ADMIN_HEADERS)).json()

    assert data["mode"] == "fair"
    by_name = {k["name"]: k for k in data["keys"]}
    assert (by_name["a"]["tokens"], by_name["b"]["tokens"]) == (300, 100)
    assert by_name["a"]["queue_wait_p95_ms"] is not None and by_name["a"]["virtual_tokens"] > 0
    assert abs(data["jain_index"] - 0.8) < 1e-6
    assert data["models"] == [{"model": settings.gemini_fast_model, "parallel": 1, "running": 0, "queued": 0}]
