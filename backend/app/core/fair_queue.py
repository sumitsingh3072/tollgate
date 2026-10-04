"""Fair queuing for upstream model slots, after the Virtual Token Counter (VTC) of Sheng et al.,
"Fairness in Serving Large Language Models" (OSDI 2024).

The gateway caps in-flight requests per upstream model (UPSTREAM_MAX_PARALLEL), so the provider's own
first-come-first-served queue stays empty and every ordering decision happens here:

1. Each key has a virtual counter of service received: input tokens + OUTPUT_WEIGHT x output tokens
   (charged at dispatch and while the response streams).
2. When a slot frees, the oldest request of the active key with the LOWEST counter runs next.
3. Counter lift: a key that becomes active again is raised to the minimum counter among active keys,
   so time spent idle cannot be banked to monopolize the model later.
4. Backpressure: at most FAIR_MAX_QUEUE_PER_KEY waiting requests per key and FAIR_MAX_WAIT_S of
   waiting, otherwise 429 with Retry-After.

Modes: "fair" (VTC), "fifo" (gateway queue, arrival order) and "off" (no gateway queue at all: the
provider's own FIFO decides). The last two exist to benchmark against.
"""

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal

from app.errors import GatewayError
from app.telemetry import metrics

Mode = Literal["fair", "fifo", "off"]


class VirtualCounters:
    """Service received per key, shared by every model's scheduler."""

    def __init__(self, output_weight: float = 2.0) -> None:
        self.output_weight = output_weight
        self._served: dict[str, float] = {}
        self._active: dict[str, int] = {}  # key -> waiting + running requests

    def value(self, key_id: str, weight: float = 1.0) -> float:
        return self._served.get(key_id, 0.0) / weight

    def activate(self, key_id: str) -> None:
        if self._active.get(key_id, 0) == 0:
            others = [self._served.get(k, 0.0) for k, n in self._active.items() if n > 0]
            if others:  # counter lift
                self._served[key_id] = max(self._served.get(key_id, 0.0), min(others))
        self._active[key_id] = self._active.get(key_id, 0) + 1

    def deactivate(self, key_id: str) -> None:
        remaining = self._active.get(key_id, 0) - 1
        if remaining > 0:
            self._active[key_id] = remaining
        else:
            self._active.pop(key_id, None)

    def charge(self, key_id: str, input_tokens: float = 0, output_tokens: float = 0) -> None:
        self._served[key_id] = self._served.get(key_id, 0.0) + input_tokens + self.output_weight * output_tokens

    def snapshot(self) -> dict[str, float]:
        return dict(self._served)

    @property
    def active(self) -> set[str]:
        return set(self._active)


@dataclass(eq=False)
class Ticket:
    key_id: str
    label: str  # key prefix, for metrics
    weight: float
    enqueued_at: float = field(default_factory=time.perf_counter)
    granted: asyncio.Future[None] = field(default_factory=lambda: asyncio.get_running_loop().create_future())
    wait_ms: int = 0


class FairScheduler:
    """Slots for one upstream model."""

    def __init__(
        self, model: str, parallel: int, counters: VirtualCounters, *, mode: Mode, max_queue: int, max_wait_s: float
    ):
        self.model = model
        self.parallel = parallel
        self.counters = counters
        self.mode = mode
        self.max_queue = max_queue
        self.max_wait_s = max_wait_s
        self._free = parallel
        self._queues: dict[str, deque[Ticket]] = {}

    @property
    def running(self) -> int:
        return self.parallel - self._free

    def depth_by_key(self) -> dict[str, int]:
        return {key: len(q) for key, q in self._queues.items() if q}

    async def acquire(self, key_id: str, label: str, weight: float = 1.0) -> Ticket:
        ticket = Ticket(key_id, label, weight)
        self.counters.activate(key_id)
        if self._free > 0 and not any(self._queues.values()):
            self._free -= 1
            self._granted(ticket)
            return ticket

        queue = self._queues.setdefault(key_id, deque())
        if len(queue) >= self.max_queue:
            self.counters.deactivate(key_id)
            raise GatewayError(
                429,
                "queue_full",
                f"Too many queued requests for this key on {self.model} (max {self.max_queue}). Retry shortly.",
                headers={"Retry-After": "1"},
            )
        queue.append(ticket)
        self._update_depth(label, key_id)
        try:
            await asyncio.wait_for(asyncio.shield(ticket.granted), timeout=self.max_wait_s)
        except TimeoutError:
            if not ticket.granted.done():
                self._withdraw(ticket)
                raise GatewayError(
                    429,
                    "queue_timeout",
                    f"Waited {self.max_wait_s:.0f}s for a {self.model} slot. The model is busy; retry shortly.",
                    headers={"Retry-After": str(max(1, round(self.max_wait_s / 2)))},
                ) from None
        except asyncio.CancelledError:
            if ticket.granted.done():
                self.release(ticket)  # granted just as we were cancelled: give the slot back
            else:
                self._withdraw(ticket)
            raise
        self._granted(ticket)
        return ticket

    def release(self, ticket: Ticket) -> None:
        self.counters.deactivate(ticket.key_id)
        self._free += 1
        self._dispatch()

    def _granted(self, ticket: Ticket) -> None:
        ticket.wait_ms = round((time.perf_counter() - ticket.enqueued_at) * 1000)
        metrics.queue_wait.labels(self.model).observe(ticket.wait_ms / 1000)

    def _withdraw(self, ticket: Ticket) -> None:
        queue = self._queues.get(ticket.key_id)
        if queue and ticket in queue:
            queue.remove(ticket)
        self.counters.deactivate(ticket.key_id)
        self._update_depth(ticket.label, ticket.key_id)

    def _dispatch(self) -> None:
        while self._free > 0:
            ticket = self._next()
            if ticket is None:
                return
            self._free -= 1
            ticket.granted.set_result(None)
            self._update_depth(ticket.label, ticket.key_id)

    def _next(self) -> Ticket | None:
        heads = [q[0] for q in self._queues.values() if q]
        if not heads:
            return None
        if self.mode == "fifo":
            ticket = min(heads, key=lambda t: t.enqueued_at)
        else:
            ticket = min(heads, key=lambda t: (self.counters.value(t.key_id, t.weight), t.enqueued_at))
        self._queues[ticket.key_id].popleft()
        return ticket

    def _update_depth(self, label: str, key_id: str) -> None:
        metrics.queue_depth.labels(label).set(len(self._queues.get(key_id, ())))
        if key_id in self._queues and not self._queues[key_id]:
            del self._queues[key_id]


class FairQueue:
    """One scheduler per upstream model, sharing the virtual counters."""

    def __init__(self, *, mode: Mode, parallel: int, max_queue: int, max_wait_s: float, output_weight: float):
        self.mode = mode
        self.counters = VirtualCounters(output_weight)
        self._settings = {"parallel": parallel, "max_queue": max_queue, "max_wait_s": max_wait_s}
        self.schedulers: dict[str, FairScheduler] = {}

    def scheduler(self, model: str) -> FairScheduler:
        if model not in self.schedulers:
            self.schedulers[model] = FairScheduler(
                model,
                self._settings["parallel"],
                self.counters,
                mode=self.mode,
                max_queue=self._settings["max_queue"],
                max_wait_s=self._settings["max_wait_s"],
            )
        return self.schedulers[model]

    async def acquire(self, model: str, key_id: str, label: str) -> Ticket | None:
        """None when the gateway queue is off (the provider schedules)."""
        if self.mode == "off":
            return None
        return await self.scheduler(model).acquire(key_id, label)

    def release(self, model: str, ticket: Ticket | None) -> None:
        if ticket is not None:
            self.scheduler(model).release(ticket)

    def charge(self, key_id: str, input_tokens: float = 0, output_tokens: float = 0) -> None:
        self.counters.charge(key_id, input_tokens, output_tokens)

    @asynccontextmanager
    async def slot(self, model: str, key_id: str, label: str) -> AsyncIterator[Ticket | None]:
        ticket = await self.acquire(model, key_id, label)
        try:
            yield ticket
        finally:
            self.release(model, ticket)
