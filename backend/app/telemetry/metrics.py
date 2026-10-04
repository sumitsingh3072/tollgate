"""Prometheus instruments, named after the OpenTelemetry GenAI semantic conventions where they exist.

Single-process registry: the gateway runs one uvicorn worker (coalescing and fair queuing are
per-process too).
"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.logging_queue import LogEvent

TOKEN_BUCKETS = (1, 4, 16, 64, 256, 1024, 4096, 16384, 65536)
DURATION_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)

token_usage = Histogram(
    "gen_ai_client_token_usage",
    "Tokens used per request.",
    ["gen_ai_request_model", "token_type"],
    buckets=TOKEN_BUCKETS,
)
operation_duration = Histogram(
    "gen_ai_client_operation_duration_seconds",
    "End-to-end request duration as seen by the gateway.",
    ["gen_ai_request_model", "status_class"],
    buckets=DURATION_BUCKETS,
)
time_to_first_token = Histogram(
    "gen_ai_server_time_to_first_token_seconds",
    "Time to the first streamed content chunk.",
    ["gen_ai_request_model"],
    buckets=DURATION_BUCKETS,
)
cache_requests = Counter("tollgate_cache_requests_total", "Cache outcomes per request.", ["status"])
cache_admission_rejected = Counter(
    "tollgate_cache_admission_rejected_total", "Cacheable responses not stored on first sighting."
)


def observe(event: LogEvent) -> None:
    """Record one finished request. Cheap, in-process, no I/O."""
    alias = event.alias
    operation_duration.labels(alias, f"{event.status // 100}xx").observe(event.latency_ms / 1000)
    if event.in_tokens or event.out_tokens:
        token_usage.labels(alias, "input").observe(event.in_tokens)
        token_usage.labels(alias, "output").observe(event.out_tokens)
    if event.ttft_ms is not None:
        time_to_first_token.labels(alias).observe(event.ttft_ms / 1000)
    if event.cache_status:
        cache_requests.labels(event.cache_status).inc()
        if event.cache_status == "admission_rejected":
            cache_admission_rejected.inc()


def render() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
