"""Per-key RPM counter and daily token quota in Redis; 429 errors.

rl:{key_id}:{epoch_minute}  fixed-window request counter (INCR + EXPIRE)
tok:{key_id}:{YYYY-MM-DD}   tokens used today, UTC (INCRBY after each response)
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis

from app.core.keys import KeyRecord
from app.errors import GatewayError

_WINDOW_SECONDS = 60
_TOKEN_KEY_TTL = int(timedelta(days=2).total_seconds())  # outlive the day even across timezones/clock skew


@dataclass(frozen=True)
class LimitState:
    rpm: int
    requests_remaining: int
    daily_token_quota: int
    tokens_remaining: int

    def headers(self) -> dict[str, str]:
        return {
            "x-ratelimit-limit-requests": str(self.rpm),
            "x-ratelimit-remaining-requests": str(self.requests_remaining),
            "x-ratelimit-limit-tokens": str(self.daily_token_quota),
            "x-ratelimit-remaining-tokens": str(self.tokens_remaining),
        }


def _rate_key(key_id: uuid.UUID, now: datetime) -> str:
    return f"rl:{key_id}:{int(now.timestamp()) // _WINDOW_SECONDS}"


def token_key(key_id: uuid.UUID, now: datetime) -> str:
    return f"tok:{key_id}:{now:%Y-%m-%d}"


def _seconds_to_midnight(now: datetime) -> int:
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - now).total_seconds()))


async def check(redis: Redis, key: KeyRecord, now: datetime | None = None) -> LimitState:
    """Count this request and enforce both limits in a single Redis round trip."""
    now = now or datetime.now(UTC)
    rate_key = _rate_key(key.id, now)
    async with redis.pipeline(transaction=False) as pipe:
        pipe.incr(rate_key)
        pipe.expire(rate_key, _WINDOW_SECONDS + 1)
        pipe.get(token_key(key.id, now))
        count, _, used_raw = await pipe.execute()

    used = int(used_raw or 0)
    if count > key.rpm:
        retry_after = _WINDOW_SECONDS - int(now.timestamp()) % _WINDOW_SECONDS
        raise GatewayError(
            429,
            "rate_limit",
            f"Rate limit reached: {key.rpm} requests per minute. Retry in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )
    if used >= key.daily_token_quota:
        raise GatewayError(
            429,
            "quota_exceeded",
            f"Daily token quota reached: {used}/{key.daily_token_quota} tokens used today (UTC).",
            headers={"Retry-After": str(_seconds_to_midnight(now))},
        )
    return LimitState(
        rpm=key.rpm,
        requests_remaining=key.rpm - count,
        daily_token_quota=key.daily_token_quota,
        tokens_remaining=key.daily_token_quota - used,
    )


async def record_tokens(redis: Redis, key_id: uuid.UUID, tokens: int, now: datetime | None = None) -> None:
    if tokens <= 0:
        return
    tok = token_key(key_id, now or datetime.now(UTC))
    async with redis.pipeline(transaction=False) as pipe:
        pipe.incrby(tok, tokens)
        pipe.expire(tok, _TOKEN_KEY_TTL)
        await pipe.execute()


async def tokens_today(redis: Redis, key_ids: list[uuid.UUID], now: datetime | None = None) -> dict[uuid.UUID, int]:
    if not key_ids:
        return {}
    now = now or datetime.now(UTC)
    values = await redis.mget([token_key(k, now) for k in key_ids])
    return {k: int(v or 0) for k, v in zip(key_ids, values, strict=True)}
