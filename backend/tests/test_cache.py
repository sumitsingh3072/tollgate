"""Cache layers: eligibility, canonical scoped key, second-sight admission, size bound, TTL, scope."""

import json

import httpx
import pytest
import respx
from fakeredis import FakeAsyncRedis

from app.config import Settings
from app.core import cache
from app.core.cache import CachePolicy

pytestmark = pytest.mark.respx(assert_all_called=False)

MESSAGES = [{"role": "user", "content": "hi"}]


def completion(content: str = "ok", finish_reason: str = "stop", **message) -> dict:
    return {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, **message},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
    }


@pytest.fixture
def gemini(settings: Settings, respx_mock: respx.MockRouter) -> respx.Route:
    return respx_mock.post(f"{settings.gemini_base_url}/chat/completions")


async def ask(client: httpx.AsyncClient, auth: dict[str, str], **body) -> httpx.Response:
    payload = {"model": "fast", "messages": MESSAGES, "temperature": 0, **body}
    return await client.post("/v1/chat/completions", json=payload, headers=auth)


async def test_second_sight_admission(client, auth, gemini) -> None:
    gemini.mock(return_value=httpx.Response(200, json=completion()))

    statuses = [(await ask(client, auth)).headers["x-tollgate-cache"] for _ in range(3)]

    # One-hit wonders never take cache space: stored on the second sighting, served on the third.
    assert statuses == ["admission_rejected", "miss", "hit"]
    assert gemini.call_count == 2


async def test_private_scope_never_shares_between_keys(client, auth, create_key, gemini) -> None:
    gemini.mock(return_value=httpx.Response(200, json=completion()))
    for _ in range(2):
        await ask(client, auth)  # now cached for the first key
    other = await create_key(rpm=100)

    resp = await ask(client, {"Authorization": f"Bearer {other['key']}"})

    assert resp.headers["x-tollgate-cache"] == "admission_rejected"  # a fresh sighting, not a hit


@pytest.mark.parametrize(
    ("reply", "why"),
    [
        (completion(finish_reason="length"), "cut off"),
        (
            completion(tool_calls=[{"id": "t", "type": "function", "function": {"name": "f", "arguments": "{}"}}]),
            "tools",
        ),
        (completion(content="x" * 20_000), "too big"),
    ],
)
async def test_incomplete_or_large_responses_not_cached(client, auth, gemini, reply, why) -> None:
    gemini.mock(return_value=httpx.Response(200, json=reply))

    statuses = [(await ask(client, auth)).headers["x-tollgate-cache"] for _ in range(3)]

    assert statuses == ["ineligible"] * 3, why


@pytest.mark.parametrize("extra", [{"temperature": 0.7}, {"tools": [{"type": "function"}]}, {"n": 2}])
async def test_nondeterministic_requests_are_ineligible(client, auth, gemini, extra) -> None:
    gemini.mock(return_value=httpx.Response(200, json=completion()))
    statuses = [(await ask(client, auth, **extra)).headers["x-tollgate-cache"] for _ in range(3)]
    assert statuses == ["ineligible"] * 3


def sse_body():
    async def gen():
        yield (
            b'data: {"id":"c1","created":1,"model":"g",'
            b'"choices":[{"delta":{"role":"assistant","content":"str"},"index":0}]}\n\n'
        )
        yield b'data: {"choices":[{"delta":{"content":"eamed"},"index":0,"finish_reason":"stop"}]}\n\n'
        yield b'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}\n\n'
        yield b"data: [DONE]\n\n"

    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=gen())


async def stream_text(client, auth, model="fast") -> tuple[str, str]:
    payload = {"model": model, "messages": MESSAGES, "temperature": 0, "stream": True}
    async with client.stream("POST", "/v1/chat/completions", json=payload, headers=auth) as resp:
        raw = b"".join([c async for c in resp.aiter_bytes()]).decode()
    content = "".join(
        json.loads(line[5:])["choices"][0]["delta"].get("content", "")
        for line in raw.splitlines()
        if line.startswith("data: {") and json.loads(line[5:])["choices"]
    )
    return resp.headers.get("x-tollgate-cache", ""), content


async def test_streams_are_cached_and_replayed(client, auth, app, gemini) -> None:
    gemini.mock(side_effect=lambda _: sse_body())

    first = await stream_text(client, auth)  # first sighting: not stored
    second = await stream_text(client, auth)  # stored
    third = await stream_text(client, auth)  # replayed from cache as SSE

    assert [first[1], second[1], third[1]] == ["streamed"] * 3
    assert third[0] == "hit" and gemini.call_count == 2
    # The same entry also answers a non-streaming request.
    resp = await ask(client, auth)
    assert resp.headers["x-tollgate-cache"] == "hit"
    assert resp.json()["choices"][0]["message"]["content"] == "streamed"
    await app.state.log_queue.flush()
    statuses = [
        i["cache_status"]
        for i in (await client.get("/admin/logs", headers={"Authorization": "Bearer test-admin"})).json()["items"]
    ]
    assert statuses == ["hit", "hit", "miss", "admission_rejected"]


async def test_shared_scope_pools_across_keys_and_hides_headers(client, auth, create_key, gemini) -> None:
    gemini.mock(return_value=httpx.Response(200, json=completion("faq answer")))
    other = await create_key(rpm=100)
    for _ in range(2):
        await ask(client, auth, model="faq")  # stored on second sight

    resp = await ask(client, {"Authorization": f"Bearer {other['key']}"}, model="faq")

    assert resp.json()["choices"][0]["message"]["content"] == "faq answer"
    assert gemini.call_count == 2  # the other key was served from the shared pool
    assert "x-tollgate-cache" not in resp.headers and "x-tollgate-coalesce" not in resp.headers


async def test_shared_insert_budget(client, auth, gemini, redis: FakeAsyncRedis, app) -> None:
    gemini.mock(return_value=httpx.Response(200, json=completion()))
    app.state.aliases["faq"] = app.state.aliases["faq"].__class__(
        chain=app.state.aliases["faq"].chain, cache=CachePolicy(scope="shared", insert_budget_per_min=1)
    )

    async def twice(prompt: str) -> None:
        for _ in range(2):
            await client.post(
                "/v1/chat/completions",
                json={"model": "faq", "messages": [{"role": "user", "content": prompt}], "temperature": 0},
                headers=auth,
            )

    await twice("one")
    await twice("two")  # over this key's budget of 1 new entry per minute: served, not stored
    assert len(await redis.keys("cache:*")) == 1


async def test_ttl_follows_route_policy(client, auth, gemini, redis: FakeAsyncRedis, settings: Settings) -> None:
    gemini.mock(return_value=httpx.Response(200, json=completion()))
    for _ in range(2):
        await ask(client, auth)
    keys = [k for k in await redis.keys("cache:*")]
    assert len(keys) == 1
    assert 0 < await redis.ttl(keys[0]) <= settings.cache_ttl
    assert await redis.ttl(f"seen:{keys[0]}") <= settings.cache_seen_ttl


def test_canonical_key_normalizes_and_scopes() -> None:
    base = {"messages": [{"role": "user", "content": "  hello   world \n"}], "temperature": 0, "user": "u1"}
    same = {"temperature": 0, "messages": [{"role": "user", "content": "hello world"}], "user": "u2", "stream": True}
    assert cache.cache_key("k1", "fast", base) == cache.cache_key("k1", "fast", same)
    assert cache.cache_key("k1", "fast", base) != cache.cache_key("k2", "fast", base)  # scope
    assert cache.cache_key("k1", "fast", base) != cache.cache_key("k1", "smart", base)  # alias
    assert cache.cache_key("k1", "fast", base) != cache.cache_key("k1", "fast", {**base, "max_tokens": 5})


def test_eligibility_rules() -> None:
    private = CachePolicy()
    assert cache.request_eligible({"temperature": 0}, private)
    assert not cache.request_eligible({}, private)  # provider default temperature is not deterministic
    assert cache.request_eligible({"temperature": 0.9}, CachePolicy(cache_nondeterministic=True))
    assert cache.encode_if_eligible("m", completion(), 16_384) is not None
    assert json.loads(cache.encode_if_eligible("m", completion(), 16_384))["model"] == "m"
    assert cache.encode_if_eligible("m", {"choices": []}, 16_384) is None


async def test_admission_marker(redis: FakeAsyncRedis) -> None:
    assert await cache.admit(redis, "cache:x", 60) is False
    assert await cache.admit(redis, "cache:x", 60) is True


async def test_cache_stats_endpoint(client, auth, app, gemini) -> None:
    gemini.mock(return_value=httpx.Response(200, json=completion()))
    for _ in range(3):
        await ask(client, auth)  # rejected, stored, hit
    await ask(client, auth, temperature=0.5)  # ineligible
    await app.state.log_queue.flush()

    stats = (await client.get("/admin/cache/stats", headers={"Authorization": "Bearer test-admin"})).json()

    assert stats["statuses"] == {"admission_rejected": 1, "miss": 1, "hit": 1, "ineligible": 1}
    assert stats["hit_rate"] == round(1 / 3, 4) and stats["admission_rejected"] == 1
    assert (stats["entries"], stats["seen_markers"]) == (1, 1)
    # fakeredis has no INFO: memory figures degrade to 0 (real Redis reports them).
    assert stats["used_memory_bytes"] >= 0 and stats["separate_instance"] is False

    overview = (await client.get("/admin/stats", headers={"Authorization": "Bearer test-admin"})).json()
    assert overview["coalesced"] == 0 and "p50_ttft_ms" in overview


async def test_cache_stats_hide_instance_figures_from_users(client, auth) -> None:
    user = {"Authorization": "Bearer test-admin", "X-Tollgate-User": "user_alice"}
    stats = (await client.get("/admin/cache/stats", headers=user)).json()
    assert stats["entries"] is None and stats["used_memory_bytes"] is None and stats["eviction_policy"] is None
