"""API key format, hashing, and the Redis key-lookup cache (key:{sha256})."""

import hashlib
import json
import secrets
import string
import uuid
from dataclasses import asdict, dataclass

from redis.asyncio import Redis

KEY_PREFIX = "tg_live_"
KEY_RANDOM_LENGTH = 32
DISPLAY_PREFIX_LENGTH = len(KEY_PREFIX) + 4  # "tg_live_ab12" is shown in the dashboard
_ALPHABET = string.ascii_letters + string.digits
_INVALID = "-"  # cached marker for unknown or revoked keys (stops DB hammering with bad keys)


@dataclass(frozen=True)
class KeyRecord:
    """What the request path needs to know about a key; cached in Redis."""

    id: uuid.UUID
    name: str
    rpm: int
    daily_token_quota: int
    prefix: str = ""  # display prefix, used as a low-cardinality metrics label


def generate_key() -> str:
    return KEY_PREFIX + "".join(secrets.choice(_ALPHABET) for _ in range(KEY_RANDOM_LENGTH))


def hash_key(raw_key: str) -> str:
    # Keys are 190 bits of randomness, so a fast unsalted hash is appropriate (no brute-force risk).
    return hashlib.sha256(raw_key.encode()).hexdigest()


def looks_like_key(raw_key: str) -> bool:
    return raw_key.startswith(KEY_PREFIX) and len(raw_key) == len(KEY_PREFIX) + KEY_RANDOM_LENGTH


def _cache_key(key_hash: str) -> str:
    return f"key:{key_hash}"


async def cache_get(redis: Redis, key_hash: str) -> KeyRecord | bool | None:
    """Returns the record, False if cached as invalid, or None on cache miss."""
    raw = await redis.get(_cache_key(key_hash))
    if raw is None:
        return None
    if raw == _INVALID:
        return False
    data = json.loads(raw)
    return KeyRecord(
        id=uuid.UUID(data["id"]),
        name=data["name"],
        rpm=data["rpm"],
        daily_token_quota=data["daily_token_quota"],
        prefix=data.get("prefix", ""),  # entries cached before the field existed
    )


async def cache_set(redis: Redis, key_hash: str, record: KeyRecord | None, ttl: int) -> None:
    value = _INVALID if record is None else json.dumps({**asdict(record), "id": str(record.id)})
    await redis.set(_cache_key(key_hash), value, ex=ttl)


async def cache_delete(redis: Redis, key_hash: str) -> None:
    await redis.delete(_cache_key(key_hash))
