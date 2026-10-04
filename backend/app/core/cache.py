"""Exact-match response cache in Redis (temperature 0, non-streaming, TTL 1h).

Key: cache:{sha256 of the canonical request body}. The whole body (alias, messages, temperature,
max_tokens, tools, response_format, ...) is hashed, so requests that differ in anything that can
change the output never share an entry.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

# Fields that never change the completion text.
_IGNORED_FIELDS = frozenset({"stream", "stream_options", "user"})


@dataclass(frozen=True)
class CachedResponse:
    model: str
    body: dict[str, Any]


def is_cacheable(body: dict[str, Any]) -> bool:
    return not body.get("stream") and body.get("temperature") == 0


def cache_key(body: dict[str, Any]) -> str:
    canonical = json.dumps(
        {k: v for k, v in body.items() if k not in _IGNORED_FIELDS},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"cache:{hashlib.sha256(canonical.encode()).hexdigest()}"


async def get(redis: Redis, key: str) -> CachedResponse | None:
    raw = await redis.get(key)
    if raw is None:
        return None
    data = json.loads(raw)
    return CachedResponse(model=data["model"], body=data["body"])


async def put(redis: Redis, key: str, model: str, body: dict[str, Any], ttl: int) -> None:
    if not body.get("choices"):
        return  # never cache empty/odd upstream replies
    await redis.set(key, json.dumps({"model": model, "body": body}, separators=(",", ":")), ex=ttl)
