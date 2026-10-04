"""Walk the alias chain; circuit breaker (3 failures -> open 30s).

Breaker state is in-process (one gateway process per deployment here). After the open window a
single trial request is allowed (half-open); success closes the breaker, failure re-opens it.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass

from app.config import Upstream
from app.errors import GatewayError

log = logging.getLogger("tollgate.fallback")


@dataclass
class _BreakerState:
    failures: int = 0
    open_until: float = 0.0


class CircuitBreakers:
    def __init__(self, failure_threshold: int, open_seconds: float, clock: Callable[[], float] = time.monotonic):
        self._threshold = failure_threshold
        self._open_seconds = open_seconds
        self._clock = clock
        self._states: dict[tuple[str, str], _BreakerState] = {}

    def _state(self, upstream: Upstream) -> _BreakerState:
        return self._states.setdefault((upstream.base_url, upstream.model), _BreakerState())

    def allows(self, upstream: Upstream) -> bool:
        return self._clock() >= self._state(upstream).open_until

    def is_open(self, upstream: Upstream) -> bool:
        return not self.allows(upstream)

    def record_success(self, upstream: Upstream) -> None:
        state = self._state(upstream)
        if state.failures >= self._threshold:
            log.info("circuit closed", extra={"model": upstream.model})
        state.failures, state.open_until = 0, 0.0

    def record_failure(self, upstream: Upstream) -> None:
        state = self._state(upstream)
        state.failures += 1
        if state.failures >= self._threshold:
            state.open_until = self._clock() + self._open_seconds
            log.warning(
                "circuit open",
                extra={"model": upstream.model, "failures": state.failures, "open_seconds": self._open_seconds},
            )


def is_retryable(error: GatewayError) -> bool:
    """Upstream-side failures (5xx, 429, timeouts, unreachable) move on to the next model; 4xx do not."""
    return error.status_code >= 500 or error.status_code == 429


@dataclass(frozen=True)
class ChainResult[T]:
    value: T
    upstream: Upstream
    fallback_used: bool


# Gateway-side errors that say nothing about the upstream's health. queue_full is a per-key limit:
# returned as-is. queue_timeout means the model is saturated: worth falling back, but not a reason
# to open the model's circuit breaker.
_RETURN_AS_IS = frozenset({"queue_full"})
_NOT_UPSTREAM_FAULT = frozenset({"queue_full", "queue_timeout"})

# The deadline for the current attempt when the attempt applies it itself (see run_chain).
current_deadline: ContextVar[float | None] = ContextVar("fallback_deadline", default=None)


async def _attempt_with_deadline[T](
    attempt: Callable[[Upstream], Awaitable[T]], upstream: Upstream, seconds: float | None
) -> T:
    try:
        async with asyncio.timeout(seconds):  # None = no deadline
            return await attempt(upstream)
    except TimeoutError as exc:
        raise GatewayError(
            504, "upstream_timeout", f"upstream {upstream.model}: no response within {seconds:g}s"
        ) from exc


async def with_deadline[T](call: Callable[[], Awaitable[T]], upstream: Upstream) -> T:
    """Apply the current attempt's fallback deadline to just `call` (e.g. the upstream request,
    excluding time spent waiting for a model slot)."""
    return await _attempt_with_deadline(lambda _: call(), upstream, current_deadline.get())


async def run_chain[T](
    alias: str,
    chain: Sequence[Upstream],
    breakers: CircuitBreakers,
    attempt: Callable[[Upstream], Awaitable[T]],
    fallback_timeout: float | None = None,
    *,
    attempt_applies_deadline: bool = False,
) -> ChainResult[T]:
    """Try each upstream in order, skipping open circuits. Raises the last error if all fail.

    fallback_timeout caps every attempt that still has a next upstream to fall back to (for streams
    that is time to first byte, since attempt returns once headers arrive). The last attempt only
    has the HTTP client's UPSTREAM_TIMEOUT. With attempt_applies_deadline the attempt receives the
    deadline through `current_deadline` and wraps only its upstream call in `with_deadline`.
    """
    candidates = [u for u in chain if breakers.allows(u)]
    if not candidates:
        # Everything is open: trying beats failing without a single attempt.
        candidates = list(chain)

    last_error: GatewayError | None = None
    for index, upstream in enumerate(candidates):
        has_next = index + 1 < len(candidates)
        deadline = fallback_timeout if has_next else None
        try:
            if attempt_applies_deadline:
                token = current_deadline.set(deadline)
                try:
                    value = await attempt(upstream)
                finally:
                    current_deadline.reset(token)
            else:
                value = await _attempt_with_deadline(attempt, upstream, deadline)
        except GatewayError as exc:
            if exc.type in _RETURN_AS_IS or not is_retryable(exc):
                raise
            if exc.type not in _NOT_UPSTREAM_FAULT:
                breakers.record_failure(upstream)
            last_error = exc
            if has_next:
                log.warning(
                    "upstream failed, falling back",
                    extra={
                        "alias": alias,
                        "model": upstream.model,
                        "error": exc.type,
                        "next": candidates[index + 1].model,
                    },
                )
            continue
        breakers.record_success(upstream)
        return ChainResult(value=value, upstream=upstream, fallback_used=upstream is not chain[0])

    assert last_error is not None
    raise last_error
