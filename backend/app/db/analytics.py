"""Dashboard aggregates over request_logs: totals, distributions, breakdowns and time series.

Every function takes its own session so the stats endpoint can run them concurrently
(see run_concurrently). Postgres-only SQL (percentile_cont, extract(epoch)) has a portable
fallback for SQLite, which the test suite uses.
"""

import asyncio
import math
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import BigInteger, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ApiKey, RequestLog

ERRORS = RequestLog.status >= 400
TOKENS = RequestLog.in_tokens + RequestLog.out_tokens
# Latency of requests an upstream model actually served (cache hits and rejections excluded).
SERVED = (RequestLog.status < 400) & RequestLog.cache_hit.is_(False)

# Upper bounds (ms) of the latency histogram bins; the last bin is open-ended.
LATENCY_BINS_MS: tuple[int, ...] = (250, 500, 1_000, 2_000, 5_000, 10_000, 30_000)
# Candidate bucket sizes for the time series, smallest first.
DAY_SECONDS = 86_400
_BUCKETS_S = (3_600, 3 * 3_600, 6 * 3_600, 12 * 3_600, DAY_SECONDS)
_MAX_POINTS = 48


@dataclass(frozen=True)
class Window:
    """A time range, optionally limited to the keys of one owner (None = operator view)."""

    since: datetime
    until: datetime
    owner_id: str | None = None

    @classmethod
    def last(cls, hours: int, owner_id: str | None = None, now: datetime | None = None) -> "Window":
        now = now or datetime.now(UTC)
        return cls(since=now - timedelta(hours=hours), until=now, owner_id=owner_id)

    def previous(self) -> "Window":
        return replace(self, since=self.since - (self.until - self.since), until=self.since)

    def where(self) -> Any:
        clause = (RequestLog.ts >= self.since) & (RequestLog.ts < self.until)
        if self.owner_id is not None:
            owned = select(ApiKey.id).where(ApiKey.owner_id == self.owner_id)
            clause = clause & RequestLog.key_id.in_(owned)
        return clause


@dataclass(frozen=True)
class StatusMix:
    success: int
    client_errors: int
    rate_limited: int
    server_errors: int


@dataclass(frozen=True)
class Totals:
    requests: int
    errors: int
    cache_hits: int
    fallbacks: int
    in_tokens: int
    out_tokens: int
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    status_mix: StatusMix
    latency_histogram: list[int]  # counts per LATENCY_BINS_MS bin (+1 open-ended)


@dataclass(frozen=True)
class KeyUsageRow:
    key_id: uuid.UUID | None
    name: str | None
    prefix: str | None
    requests: int
    tokens: int
    errors: int


@dataclass(frozen=True)
class GroupUsageRow:
    name: str | None
    requests: int
    tokens: int
    errors: int
    avg_latency_ms: float | None


@dataclass(frozen=True)
class SeriesPoint:
    ts: datetime
    requests: int
    errors: int
    cache_hits: int
    fallbacks: int
    in_tokens: int
    out_tokens: int
    avg_latency_ms: float | None


def _is_postgres(session: AsyncSession) -> bool:
    return session.bind.dialect.name == "postgresql"


def percentile(sorted_values: list[int], q: float) -> float | None:
    """Linear interpolation, identical to Postgres percentile_cont."""
    if not sorted_values:
        return None
    pos = (len(sorted_values) - 1) * q
    lower, upper = math.floor(pos), math.ceil(pos)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (pos - lower)


async def _latency_percentiles(session: AsyncSession, window: Window) -> tuple[float | None, float | None]:
    if _is_postgres(session):
        latency = RequestLog.latency_ms.asc()
        row = (
            await session.execute(
                select(
                    func.percentile_cont(0.5).within_group(latency),
                    func.percentile_cont(0.95).within_group(latency),
                ).where(window.where())
            )
        ).one()
        return row[0], row[1]
    values = sorted((await session.scalars(select(RequestLog.latency_ms).where(window.where()))).all())
    return percentile(values, 0.5), percentile(values, 0.95)


def _histogram_columns() -> list[Any]:
    columns, lower = [], 0
    for upper in LATENCY_BINS_MS:
        columns.append(func.count().filter(SERVED & (RequestLog.latency_ms >= lower) & (RequestLog.latency_ms < upper)))
        lower = upper
    columns.append(func.count().filter(SERVED & (RequestLog.latency_ms >= lower)))
    return columns


async def totals(session: AsyncSession, window: Window) -> Totals:
    """Headline numbers, status mix and latency histogram in a single scan."""
    histogram = _histogram_columns()
    row = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(ERRORS),
                func.count().filter(RequestLog.cache_hit.is_(True)),
                func.count().filter(RequestLog.fallback_used.is_(True)),
                func.coalesce(func.sum(RequestLog.in_tokens), 0),
                func.coalesce(func.sum(RequestLog.out_tokens), 0),
                func.count().filter(RequestLog.status < 400),
                func.count().filter(
                    (RequestLog.status >= 400) & (RequestLog.status < 500) & (RequestLog.status != 429)
                ),
                func.count().filter(RequestLog.status == 429),
                func.count().filter(RequestLog.status >= 500),
                *histogram,
            ).where(window.where())
        )
    ).one()
    values = [int(v) for v in row]
    p50, p95 = await _latency_percentiles(session, window)
    return Totals(
        *values[:6],
        p50_latency_ms=p50,
        p95_latency_ms=p95,
        status_mix=StatusMix(*values[6:10]),
        latency_histogram=values[10:],
    )


async def counts_by(session: AsyncSession, window: Window, column: Any) -> dict[str | None, int]:
    """Request counts grouped by a categorical column (cache_status, coalesce_role, ...)."""
    result = await session.execute(select(column, func.count()).where(window.where()).group_by(column))
    return {value: int(n) for value, n in result.all()}


async def usage_by_key(session: AsyncSession, window: Window) -> list[KeyUsageRow]:
    tokens = func.coalesce(func.sum(TOKENS), 0)
    result = await session.execute(
        select(RequestLog.key_id, ApiKey.name, ApiKey.prefix, func.count(), tokens, func.count().filter(ERRORS))
        .outerjoin(ApiKey, ApiKey.id == RequestLog.key_id)
        .where(window.where())
        .group_by(RequestLog.key_id, ApiKey.name, ApiKey.prefix)
        .order_by(tokens.desc())
    )
    return [KeyUsageRow(*row) for row in result.all()]


async def _usage_by(session: AsyncSession, window: Window, column: Any) -> list[GroupUsageRow]:
    avg_latency = func.avg(case((SERVED, RequestLog.latency_ms)))
    result = await session.execute(
        select(column, func.count(), func.coalesce(func.sum(TOKENS), 0), func.count().filter(ERRORS), avg_latency)
        .where(window.where())
        .group_by(column)
        .order_by(func.count().desc())
    )
    return [
        GroupUsageRow(name, int(n), int(tokens), int(errors), float(avg) if avg is not None else None)
        for name, n, tokens, errors, avg in result.all()
    ]


async def usage_by_alias(session: AsyncSession, window: Window) -> list[GroupUsageRow]:
    return await _usage_by(session, window, RequestLog.alias)


async def usage_by_model(session: AsyncSession, window: Window) -> list[GroupUsageRow]:
    return await _usage_by(session, window, RequestLog.model_used)


def bucket_seconds(window: Window) -> int:
    span = (window.until - window.since).total_seconds()
    return next((b for b in _BUCKETS_S if span / b <= _MAX_POINTS), _BUCKETS_S[-1])


async def timeseries(session: AsyncSession, window: Window, bucket: int) -> list[SeriesPoint]:
    """Per-bucket counts, zero-filled so charts get a continuous x axis."""
    # Postgres CAST(numeric AS bigint) rounds, so floor first; SQLite's %s is already whole seconds.
    if _is_postgres(session):
        seconds = func.floor(func.extract("epoch", RequestLog.ts))
    else:
        seconds = func.strftime("%s", RequestLog.ts)
    # // is SQL integer division in SQLAlchemy (plain / would yield decimals).
    epoch = ((cast(seconds, BigInteger) // bucket) * bucket).label("bucket")
    result = await session.execute(
        select(
            epoch,
            func.count(),
            func.count().filter(ERRORS),
            func.count().filter(RequestLog.cache_hit.is_(True)),
            func.count().filter(RequestLog.fallback_used.is_(True)),
            func.coalesce(func.sum(RequestLog.in_tokens), 0),
            func.coalesce(func.sum(RequestLog.out_tokens), 0),
            func.avg(case((SERVED, RequestLog.latency_ms))),
        )
        .where(window.where())
        .group_by(epoch)
    )
    rows = {int(r[0]): r[1:] for r in result.all()}

    first = int(window.since.timestamp()) // bucket * bucket
    last = int(window.until.timestamp()) // bucket * bucket
    points = []
    for start in range(first, last + bucket, bucket):
        n, errors, hits, fallbacks, tin, tout, avg = rows.get(start, (0, 0, 0, 0, 0, 0, None))
        points.append(
            SeriesPoint(
                ts=datetime.fromtimestamp(start, UTC),
                requests=int(n),
                errors=int(errors),
                cache_hits=int(hits),
                fallbacks=int(fallbacks),
                in_tokens=int(tin),
                out_tokens=int(tout),
                avg_latency_ms=round(float(avg), 1) if avg is not None else None,
            )
        )
    return points


async def run_concurrently(
    sessionmaker: async_sessionmaker[AsyncSession], *queries: Callable[[AsyncSession], Awaitable[Any]]
) -> list[Any]:
    """Run each query in its own session at the same time (one round trip of wall time on Neon).

    SQLite (tests) shares a single connection, so there the queries run one after another.
    """

    async def one(query: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
        async with sessionmaker() as session:
            return await query(session)

    async with sessionmaker() as probe:
        sequential = not _is_postgres(probe)
    if sequential:
        return [await one(q) for q in queries]
    return list(await asyncio.gather(*(one(q) for q in queries)))
