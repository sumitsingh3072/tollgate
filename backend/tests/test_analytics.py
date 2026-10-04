import uuid
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI

from app.db import analytics
from app.logging_queue import LogEvent, LogQueue
from tests.conftest import ADMIN_HEADERS

NOW = datetime.now(UTC)


def event(minutes_ago: float = 1, **overrides) -> LogEvent:
    base = dict(
        ts=NOW - timedelta(minutes=minutes_ago),
        key_id=None,
        alias="fast",
        model_used="m",
        in_tokens=2,
        out_tokens=3,
        latency_ms=300,
        status=200,
        cache_hit=False,
        fallback_used=False,
    )
    return LogEvent(**{**base, **overrides})


async def seed(app: FastAPI, *events: LogEvent) -> None:
    queue: LogQueue = app.state.log_queue
    for e in events:
        queue.enqueue(e)
    await queue.flush()


async def test_status_mix_histogram_and_previous_window(client, app: FastAPI) -> None:
    await seed(
        app,
        event(latency_ms=100),
        event(latency_ms=700),
        event(latency_ms=40_000, alias="smart"),
        event(latency_ms=5, cache_hit=True),  # cache hits excluded from the latency histogram
        event(status=404, model_used=None),
        event(status=429, model_used=None),
        event(status=503),
        event(minutes_ago=60 * 30, status=500),  # previous 24h window
    )

    stats = (await client.get("/admin/stats?hours=24", headers=ADMIN_HEADERS)).json()

    assert stats["status_mix"] == {"success": 4, "client_errors": 1, "rate_limited": 1, "server_errors": 1}
    counts = {(b["lower_ms"], b["upper_ms"]): b["count"] for b in stats["latency_histogram"]}
    assert counts[(0, 250)] == 1 and counts[(500, 1000)] == 1 and counts[(30000, None)] == 1
    assert sum(counts.values()) == 3
    assert (stats["previous"]["requests"], stats["previous"]["errors"]) == (1, 1)
    aliases = {a["name"]: a for a in stats["by_alias"]}
    assert aliases["smart"]["avg_latency_ms"] == 40_000
    assert aliases["fast"]["requests"] == 6


async def test_series_is_zero_filled_and_bucketed(client, app: FastAPI) -> None:
    await seed(app, event(minutes_ago=1), event(minutes_ago=2), event(minutes_ago=60 * 5, status=500))

    stats = (await client.get("/admin/stats?hours=24", headers=ADMIN_HEADERS)).json()

    assert stats["bucket_seconds"] == 3600
    assert len(stats["series"]) in (24, 25)  # depends on where "now" falls inside the hour
    assert sum(p["requests"] for p in stats["series"]) == 3
    assert sum(p["errors"] for p in stats["series"]) == 1
    assert stats["series"][-1]["requests"] >= 1
    week = (await client.get("/admin/stats?hours=168", headers=ADMIN_HEADERS)).json()
    assert week["bucket_seconds"] == 6 * 3600


async def test_activity_heatmap_days(client, app: FastAPI) -> None:
    await seed(app, event(minutes_ago=1, in_tokens=10, out_tokens=5), event(minutes_ago=60 * 24 * 3, status=500))

    days = (await client.get("/admin/activity?days=30", headers=ADMIN_HEADERS)).json()

    assert len(days) in (30, 31)
    today = days[-1]
    assert today["date"] == f"{NOW:%Y-%m-%d}" and today["requests"] == 1 and today["tokens"] == 15
    assert sum(d["errors"] for d in days) == 1


def test_bucket_seconds() -> None:
    assert analytics.bucket_seconds(analytics.Window.last(24)) == 3600
    assert analytics.bucket_seconds(analytics.Window.last(168)) == 6 * 3600
    assert analytics.bucket_seconds(analytics.Window.last(720)) == 86_400


def test_previous_window() -> None:
    window = analytics.Window(since=NOW - timedelta(hours=24), until=NOW)
    assert window.previous() == analytics.Window(since=NOW - timedelta(hours=48), until=NOW - timedelta(hours=24))


async def test_key_usage_still_grouped(client, app: FastAPI, create_key) -> None:
    key = await create_key(name="k")
    await seed(app, event(key_id=uuid.UUID(key["id"])), event(key_id=uuid.UUID(key["id"])))
    stats = (await client.get("/admin/stats", headers=ADMIN_HEADERS)).json()
    assert stats["by_key"][0]["requests"] == 2 and stats["by_key"][0]["tokens"] == 10
