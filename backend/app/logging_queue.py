"""In-memory log queue + background flusher, batch insert every LOG_FLUSH_INTERVAL s.

The request path only appends to a list (no I/O). A background task bulk-inserts batches into
request_logs; a failed batch is kept for the next cycle as long as the buffer has room.
"""

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.usage import Usage
from app.db.models import RequestLog

log = logging.getLogger("tollgate.logqueue")


@dataclass(frozen=True, slots=True)
class LogEvent:
    ts: datetime
    key_id: uuid.UUID | None
    alias: str
    model_used: str | None
    in_tokens: int
    out_tokens: int
    latency_ms: int
    status: int
    cache_hit: bool
    fallback_used: bool


@dataclass(slots=True)
class RequestRecord:
    """Filled in while a request is handled; finish() freezes it into a LogEvent."""

    key_id: uuid.UUID | None
    alias: str
    status: int = 500
    model_used: str | None = None
    usage: Usage | None = None
    cache_hit: bool = False
    fallback_used: bool = False
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))
    started: float = field(default_factory=time.perf_counter)

    def finish(self) -> LogEvent:
        prompt = self.usage.prompt_tokens if self.usage else 0
        total = self.usage.total_tokens if self.usage else 0
        return LogEvent(
            ts=self.ts,
            key_id=self.key_id,
            alias=self.alias,
            model_used=self.model_used,
            in_tokens=prompt,
            # out = total - in, so in + out always equals what the quota was charged (incl. thinking tokens).
            out_tokens=max(total - prompt, 0),
            latency_ms=round((time.perf_counter() - self.started) * 1000),
            status=self.status,
            cache_hit=self.cache_hit,
            fallback_used=self.fallback_used,
        )


class LogQueue:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        interval: float,
        max_buffer: int = 10_000,
        max_batch: int = 1_000,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._interval = interval
        self._max_buffer = max_buffer
        self._max_batch = max_batch
        self._buffer: list[LogEvent] = []
        self._dropped = 0
        self._task: asyncio.Task[None] | None = None

    def __len__(self) -> int:
        return len(self._buffer)

    def enqueue(self, event: LogEvent) -> None:
        """Request path: O(1), never blocks, never touches the network."""
        if len(self._buffer) >= self._max_buffer:
            self._dropped += 1
            return
        self._buffer.append(event)

    async def flush(self) -> int:
        """Insert everything buffered right now. Returns the number of rows written."""
        written = 0
        while self._buffer:
            batch, self._buffer = self._buffer[: self._max_batch], self._buffer[self._max_batch :]
            try:
                async with self._sessionmaker() as session:
                    await session.execute(insert(RequestLog), [asdict(e) for e in batch])
                    await session.commit()
            except Exception:
                room = self._max_buffer - len(self._buffer)
                self._buffer = batch[:room] + self._buffer  # retry next cycle
                log.exception("log flush failed", extra={"batch": len(batch), "requeued": min(room, len(batch))})
                break
            written += len(batch)
        if self._dropped:
            log.warning("log buffer full, events dropped", extra={"dropped": self._dropped})
            self._dropped = 0
        return written

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            await self.flush()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="log-flusher")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self.flush()
