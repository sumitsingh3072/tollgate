"""Walk the alias chain; circuit breaker (3 failures -> open 30s).

Breaker state is in-process (one gateway process per deployment here). After the open window a
single trial request is allowed (half-open); success closes the breaker, failure re-opens it.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
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


async def run_chain[T](
    alias: str,
    chain: Sequence[Upstream],
    breakers: CircuitBreakers,
    attempt: Callable[[Upstream], Awaitable[T]],
    fallback_timeout: float | None = None,
) -> ChainResult[T]:
    """Try each upstream in order, skipping open circuits. Raises the last error if all fail.

    fallback_timeout caps every attempt that still has a next upstream to fall back to (for streams
    that is time to first byte, since attempt returns once headers arrive). The last attempt only
    has the HTTP client's UPSTREAM_TIMEOUT.
    """
    candidates = [u for u in chain if breakers.allows(u)]
    if not candidates:
        # Everything is open: trying beats failing without a single attempt.
        candidates = list(chain)

    last_error: GatewayError | None = None
    for index, upstream in enumerate(candidates):
        has_next = index + 1 < len(candidates)
        try:
            value = await _attempt_with_deadline(attempt, upstream, fallback_timeout if has_next else None)
        except GatewayError as exc:
            if not is_retryable(exc):
                raise
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
