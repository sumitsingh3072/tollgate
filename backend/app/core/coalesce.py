"""Request coalescing (singleflight with stream fan-out).

Identical cache-eligible requests that are in flight at the same time share one upstream call: the
first becomes the leader, the rest follow and receive the same response. Every upstream call runs in
a Flight, whose task is independent of any client connection:

- followers replay the chunks buffered so far, then wait for new ones (late joiners get everything);
- if the leader's client disconnects, followers keep receiving; the upstream call is cancelled only
  when the last subscriber leaves;
- if the upstream fails, every subscriber gets the same error.

Non-coalescable requests use a private Flight (role "none") so all requests share one code path.
Coalescing is per process, so the gateway runs a single uvicorn worker.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.errors import GatewayError

log = logging.getLogger("tollgate.coalesce")

Role = Literal["none", "leader", "follower"]


class Flight:
    def __init__(self, key: str | None) -> None:
        self.key = key
        self.chunks: list[bytes] = []
        self.result: Any = None
        self.error: BaseException | None = None
        self.done = False
        # Set by the leader once the upstream answered (model, fallback) or the call failed.
        self.model: str | None = None
        self.fallback_used = False
        self.queue_wait_ms: int | None = None
        self.cache_status: str | None = None
        self.followers = 0
        self.subscribers = 0
        self.cancelling = False  # nobody listens any more; new requests must not join
        self.task: asyncio.Task[None] | None = None
        self._changed = asyncio.Condition()
        self._ready = asyncio.Event()

    # --- producer side (the flight task) -------------------------------------------------------

    def set_meta(self, model: str, fallback_used: bool) -> None:
        self.model, self.fallback_used = model, fallback_used
        self._ready.set()

    async def emit(self, chunk: bytes) -> None:
        self.chunks.append(chunk)
        async with self._changed:
            self._changed.notify_all()

    async def _finish(self, result: Any = None, error: BaseException | None = None) -> None:
        self.result, self.error, self.done = result, error, True
        self._ready.set()
        async with self._changed:
            self._changed.notify_all()

    # --- consumer side ------------------------------------------------------------------------

    async def wait_ready(self) -> None:
        """Until the upstream answered; re-raises the upstream error if it failed first."""
        await self._ready.wait()
        if self.error is not None and self.model is None:
            raise self.error

    async def wait_result(self) -> Any:
        async with self._changed:
            await self._changed.wait_for(lambda: self.done)
        if self.error is not None:
            raise self.error
        return self.result

    async def replay(self) -> AsyncIterator[bytes]:
        """Every chunk, from the first, as it becomes available; re-raises a mid-stream failure once
        the buffered chunks are delivered."""
        index = 0
        while True:
            async with self._changed:
                await self._changed.wait_for(lambda seen=index: seen < len(self.chunks) or self.done)
            while index < len(self.chunks):
                yield self.chunks[index]
                index += 1
            if self.done and index >= len(self.chunks):
                if self.error is not None:
                    raise self.error
                return


@dataclass
class CoalesceStats:
    """Since process start (logs hold the windowed history)."""

    flights: int = 0
    followers: int = 0
    largest_fanout: int = 0


class Coalescer:
    def __init__(self) -> None:
        self._flights: dict[str, Flight] = {}
        self.stats = CoalesceStats()

    @property
    def in_flight(self) -> int:
        return len(self._flights)

    def join(self, key: str | None, start: Callable[[Flight], Awaitable[Any]]) -> tuple[Flight, Role]:
        """Attach to an identical in-flight request, or start a new flight running `start`."""
        existing = self._flights.get(key) if key is not None else None
        if existing is not None and not existing.done and not existing.cancelling:
            existing.followers += 1
            existing.subscribers += 1
            self.stats.followers += 1
            self.stats.largest_fanout = max(self.stats.largest_fanout, existing.followers + 1)
            return existing, "follower"

        flight = Flight(key)
        flight.subscribers = 1
        if key is not None:
            self._flights[key] = flight
            self.stats.flights += 1
        flight.task = asyncio.create_task(self._run(flight, start), name=f"flight:{(key or 'solo')[:20]}")
        return flight, "leader" if key is not None else "none"

    def leave(self, flight: Flight) -> None:
        """A subscriber is gone (finished or disconnected). Synchronous: safe in finally blocks."""
        flight.subscribers -= 1
        if flight.subscribers <= 0 and not flight.done and flight.task is not None:
            # Nobody is listening any more. Unregister now so an identical request arriving while the
            # task unwinds (closing the upstream connection takes a moment) starts a fresh flight.
            flight.cancelling = True
            if flight.key is not None and self._flights.get(flight.key) is flight:
                del self._flights[flight.key]
            flight.task.cancel()

    async def _run(self, flight: Flight, start: Callable[[Flight], Awaitable[Any]]) -> None:
        try:
            result = await start(flight)
        except asyncio.CancelledError:
            # Subscribers get a normal gateway error, never a CancelledError (which would escape
            # request handling as an unlogged 500).
            cancelled = GatewayError(503, "upstream_cancelled", "The shared upstream call was cancelled; retry.")
            await asyncio.shield(flight._finish(error=cancelled))
            raise
        except Exception as exc:  # delivered to every subscriber
            await flight._finish(error=exc)
        else:
            await flight._finish(result=result)
        finally:
            if flight.key is not None and self._flights.get(flight.key) is flight:
                del self._flights[flight.key]

    async def shutdown(self) -> None:
        for flight in list(self._flights.values()):
            if flight.task:
                flight.task.cancel()
        for flight in list(self._flights.values()):
            if flight.task:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await flight.task
