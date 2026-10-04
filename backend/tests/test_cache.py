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


async def test_stream_bypasses_cache(client, auth, gemini) -> None:
    async def sse():
        yield b'data: {"choices":[{"delta":{"content":"ok"},"index":0}]}\n\ndata: [DONE]\n\n'

    gemini.mock(return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse()))
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": "fast", "messages": MESSAGES, "temperature": 0, "stream": True},
        headers=auth,
    ) as resp:
        assert resp.headers["x-tollgate-cache"] == "bypass"


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
