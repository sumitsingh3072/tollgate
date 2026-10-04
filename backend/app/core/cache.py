"""Response cache with defenses against bloat (one-hit wonders) and cross-tenant leakage.

Layers:
1. Eligibility: deterministic requests only (temperature 0, unless the route opts in), and only
   complete answers (finish_reason "stop", no tool calls, at most CACHE_MAX_ENTRY_BYTES).
2. Canonical key: sha256(scope | alias | canonical JSON of the request), with message text trimmed
   and whitespace collapsed so trivial formatting differences still hit.
3. Admission on second sight (simplified TinyLFU): a response is stored only if the same key was
   already seen within CACHE_SEEN_TTL. A ~100 byte "seen:" marker stands in for the first sighting.
4. Bounded memory: entries live in a separate Redis (allkeys-lfu, maxmemory) so cache pressure can
   never evict rate-limit counters or quotas.
5. Scope: private (default) keys include the API key id, so tenants never share entries.
   Shared scope (opt-in per route, for public content) pools entries across keys, with a per-key
   insert budget so one tenant cannot flood the pool, and hides cache headers from callers.
6. TTL per route (default 24h).

Streamed responses are rebuilt into one completion and cached like any other; a hit is replayed as
JSON or as a fast SSE stream, whichever the caller asked for.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

from redis.asyncio import Redis

from app.core.usage import SSEUsageTracker

CacheStatus = Literal["hit", "miss", "admission_rejected", "ineligible", "bypass"]
Scope = Literal["private", "shared"]

# Fields that never change the completion text.
_IGNORED_FIELDS = frozenset({"stream", "stream_options", "user"})
# Requests whose output depends on more than the prompt, or that ask for several answers.
_UNCACHEABLE_FIELDS = frozenset({"tools", "functions", "tool_choice", "function_call", "logprobs", "seed"})
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class CachePolicy:
    scope: Scope = "private"
    ttl_seconds: int = 86_400
    # Cache temperature > 0 too (callers then get the same "random" answer); off by default.
    cache_nondeterministic: bool = False
    # Shared scope only: new entries a single key may add per minute.
    insert_budget_per_min: int = 30


@dataclass(frozen=True)
class CachedResponse:
    model: str
    body: dict[str, Any]


def request_eligible(body: dict[str, Any], policy: CachePolicy) -> bool:
    if any(field in body for field in _UNCACHEABLE_FIELDS) or body.get("n", 1) != 1:
        return False
    return body.get("temperature") == 0 or policy.cache_nondeterministic


def _normalize_text(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            content = _normalize_text(content)
        elif isinstance(content, list):
            content = [
                {**part, "text": _normalize_text(part["text"])} if isinstance(part.get("text"), str) else part
                for part in content
                if isinstance(part, dict)
            ]
        normalized.append({**message, "content": content})
    return normalized


def scope_id(policy: CachePolicy, key_id: str, alias: str) -> str:
    return key_id if policy.scope == "private" else f"shared:{alias}"


def cache_key(scope: str, alias: str, body: dict[str, Any]) -> str:
    """sha256(scope | alias | canonical request). Every field except stream/user is part of the key,
    so requests that could produce different answers never collide."""
    request = {k: v for k, v in body.items() if k not in _IGNORED_FIELDS and k != "model"}
    request["messages"] = _normalize_messages(body.get("messages", []))
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(f"{scope}|{alias}|{canonical}".encode()).hexdigest()
    return f"cache:{digest}"


def encode_if_eligible(model: str, body: dict[str, Any], max_bytes: int) -> str | None:
    """The stored form of a response, or None if it must not be cached."""
    choices = body.get("choices") or []
    if len(choices) != 1:
        return None
    choice = choices[0]
    message = choice.get("message") or {}
    if choice.get("finish_reason") != "stop" or message.get("tool_calls") or message.get("function_call"):
        return None
    encoded = json.dumps({"model": model, "body": body}, separators=(",", ":"))
    return encoded if len(encoded.encode()) <= max_bytes else None


async def get(redis_cache: Redis, key: str) -> CachedResponse | None:
    raw = await redis_cache.get(key)
    if raw is None:
        return None
    data = json.loads(raw)
    return CachedResponse(model=data["model"], body=data["body"])


async def admit(redis_cache: Redis, key: str, seen_ttl: int) -> bool:
    """Second-sight admission: the first sighting only leaves a small marker."""
    first_sighting = await redis_cache.set(f"seen:{key}", 1, nx=True, ex=seen_ttl)
    return not first_sighting


async def put(redis_cache: Redis, key: str, encoded: str, ttl: int) -> None:
    await redis_cache.set(key, encoded, ex=ttl)


async def within_insert_budget(redis_state: Redis, key_id: str, budget: int) -> bool:
    """Shared scope: count this insert against the key's per-minute budget (state Redis)."""
    bucket = f"cache_inserts:{key_id}:{int(time.time()) // 60}"
    async with redis_state.pipeline(transaction=False) as pipe:
        pipe.incr(bucket)
        pipe.expire(bucket, 61)
        count, _ = await pipe.execute()
    return count <= budget


def completion_from_stream(tracker: SSEUsageTracker, model: str) -> dict[str, Any] | None:
    """Rebuild a streamed answer as one chat.completion, or None if it can't be cached."""
    if tracker.tool_calls or tracker.finish_reason is None:
        return None
    body: dict[str, Any] = {
        "id": tracker.meta.get("id", "chatcmpl-tollgate"),
        "object": "chat.completion",
        "created": tracker.meta.get("created", int(time.time())),
        "model": tracker.meta.get("model", model),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": tracker.content},
                "finish_reason": tracker.finish_reason,
            }
        ],
    }
    if tracker.raw_usage:
        body["usage"] = tracker.raw_usage
    return body


def render_sse(body: dict[str, Any]) -> list[bytes]:
    """Replay a cached completion as an OpenAI-style stream (content, finish, usage, [DONE])."""
    base = {
        "id": body.get("id", "chatcmpl-tollgate"),
        "object": "chat.completion.chunk",
        "created": body.get("created", 0),
        "model": body.get("model", ""),
    }
    choice = body["choices"][0]
    content = (choice.get("message") or {}).get("content") or ""
    events: list[dict[str, Any]] = [
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason")}]},
    ]
    if body.get("usage"):
        events.append({**base, "choices": [], "usage": body["usage"]})
    return [f"data: {json.dumps(e, separators=(',', ':'))}\n\n".encode() for e in events] + [b"data: [DONE]\n\n"]
