"""Fill a database with a year of realistic synthetic traffic for demos and screenshots.

Writes demo keys (names start with "demo-") and request_logs rows. Refuses to touch a database
unless it is passed explicitly, so a real deployment is never seeded by accident.

Usage (from backend/): python -m scripts.seed_demo --database-url postgresql://tollgate:tollgate@localhost:5432/tollgate
"""

import argparse
import asyncio
import math
import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import normalize_database_url
from app.core.keys import DISPLAY_PREFIX_LENGTH, generate_key, hash_key
from app.db.models import ApiKey, RequestLog
from app.db.session import init_db

ALIASES = [  # alias, weight, primary model, base latency ms
    ("fast", 0.6, "gemma-4-26b-a4b-it", 1_100),
    ("smart", 0.22, "gemma-4-31b-it", 24_000),
    ("smart-terse", 0.13, "gemma-4-31b-it", 15_000),
    ("demo-failover", 0.05, "gemma-4-26b-a4b-it", 1_300),
]
FAST_MODEL = "gemma-4-26b-a4b-it"


def daily_volume(day: datetime, days_ago: int, rng: random.Random) -> int:
    growth = 8 + 60 * math.exp(-days_ago / 120)  # adoption ramps up over the year
    weekday = 1.0 if day.weekday() < 5 else 0.35
    if rng.random() < 0.08:  # occasional quiet days
        return 0
    return max(0, int(rng.gauss(growth * weekday, growth * 0.3)))


def make_request(ts: datetime, key_id: uuid.UUID, rng: random.Random) -> dict:
    alias, _, model, base = rng.choices(ALIASES, weights=[a[1] for a in ALIASES])[0]
    roll = rng.random()
    if roll < 0.02:
        status, model_used = 429, None
    elif roll < 0.03:
        status, model_used = 404, None
    elif roll < 0.04:
        status, model_used = 503, model
    else:
        status, model_used = 200, model
    cache_hit = status == 200 and alias == "fast" and rng.random() < 0.18
    fallback = status == 200 and (alias == "demo-failover" or (alias.startswith("smart") and rng.random() < 0.07))
    if fallback:
        model_used = FAST_MODEL
    if cache_hit:
        latency, tin, tout = rng.randint(2, 9), 0, 0
    elif model_used is None:
        latency, tin, tout = rng.randint(1, 6), 0, 0
    else:
        latency = int(rng.lognormvariate(math.log(1_200 if fallback else base), 0.45))
        tin = rng.randint(20, 900)
        tout = rng.randint(30, 260 if alias == "smart-terse" else 900)
    return dict(
        ts=ts,
        key_id=key_id,
        alias=alias,
        model_used=model_used,
        in_tokens=tin,
        out_tokens=tout,
        latency_ms=latency,
        status=status,
        cache_hit=cache_hit,
        fallback_used=fallback,
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    engine = create_async_engine(normalize_database_url(args.database_url))
    await init_db(engine)
    keys = []
    demo_keys = (("demo-backend", 600, 5_000_000), ("demo-n8n", 120, 1_000_000), ("demo-notebook", 30, 200_000))
    for name, rpm, quota in demo_keys:
        raw = generate_key()
        keys.append(
            dict(
                id=uuid.uuid4(),
                name=name,
                key_hash=hash_key(raw),
                prefix=raw[:DISPLAY_PREFIX_LENGTH],
                rpm=rpm,
                daily_token_quota=quota,
                created_at=datetime.now(UTC) - timedelta(days=args.days),
            )
        )
    key_weights = [0.65, 0.25, 0.10]

    now = datetime.now(UTC)
    rows = []
    for days_ago in range(args.days, -1, -1):
        day = (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)
        for _ in range(daily_volume(day, days_ago, rng)):
            # Business-hours bias: most traffic between 08:00 and 20:00 UTC.
            hour = min(23, max(0, int(rng.gauss(14, 4))))
            ts = day + timedelta(hours=hour, minutes=rng.randint(0, 59), seconds=rng.randint(0, 59))
            if ts > now:
                continue
            key = rng.choices(keys, weights=key_weights)[0]
            rows.append(make_request(ts, key["id"], rng))

    async with engine.begin() as conn:
        await conn.execute(insert(ApiKey), keys)
        for i in range(0, len(rows), 2_000):
            await conn.execute(insert(RequestLog), rows[i : i + 2_000])
    await engine.dispose()
    print(f"seeded {len(keys)} demo keys and {len(rows)} requests over {args.days} days")


if __name__ == "__main__":
    asyncio.run(main())
