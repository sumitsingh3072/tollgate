"""OpenAI-compatible request/response shapes. Unknown fields are allowed and forwarded unchanged."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]] | None = None


class ChatCompletionRequest(BaseModel):
    """Only the fields the gateway acts on are typed; everything else passes through."""

    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)

    def upstream_body(self) -> dict[str, Any]:
        # exclude_unset: forward exactly what the client sent, nothing we defaulted.
        return self.model_dump(exclude_unset=True)


class ModelCard(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = 0
    owned_by: str = "tollgate"


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelCard]


def _as_utc(value: datetime) -> datetime:
    # Some drivers (SQLite in tests) drop tzinfo; timestamps are always stored in UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


class KeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    rpm: int = Field(default=60, ge=1, le=100_000)
    daily_token_quota: int = Field(default=100_000, ge=1, le=1_000_000_000)


class KeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str
    rpm: int
    daily_token_quota: int
    created_at: UtcDatetime
    revoked_at: UtcDatetime | None
    tokens_today: int = 0


class KeyCreated(KeyOut):
    key: str = Field(description="Full API key. Returned only once; store it now.")


class KeyUsage(BaseModel):
    key_id: uuid.UUID | None
    name: str | None
    prefix: str | None
    requests: int
    tokens: int
    errors: int


class GroupUsage(BaseModel):
    name: str | None
    requests: int
    tokens: int
    errors: int
    avg_latency_ms: float | None


class StatusMix(BaseModel):
    success: int
    client_errors: int = Field(description="4xx other than 429")
    rate_limited: int
    server_errors: int


class LatencyBin(BaseModel):
    lower_ms: int
    upper_ms: int | None = Field(description="None for the open-ended last bin")
    count: int


class PeriodTotals(BaseModel):
    requests: int
    errors: int
    error_rate: float
    cache_hits: int
    cache_hit_rate: float
    fallbacks: int
    in_tokens: int
    out_tokens: int
    p50_latency_ms: float | None
    p95_latency_ms: float | None


class SeriesPoint(BaseModel):
    ts: UtcDatetime
    requests: int
    errors: int
    cache_hits: int
    fallbacks: int
    in_tokens: int
    out_tokens: int
    avg_latency_ms: float | None


class Stats(PeriodTotals):
    window_hours: int
    previous: PeriodTotals = Field(description="Same-length window immediately before this one")
    status_mix: StatusMix
    latency_histogram: list[LatencyBin] = Field(description="Upstream-served requests only")
    bucket_seconds: int
    series: list[SeriesPoint]
    by_key: list[KeyUsage]
    by_alias: list[GroupUsage]
    by_model: list[GroupUsage]


class ActivityDay(BaseModel):
    date: str = Field(description="UTC day, YYYY-MM-DD")
    requests: int
    tokens: int
    errors: int


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: UtcDatetime
    key_id: uuid.UUID | None
    key_name: str | None = None
    key_prefix: str | None = None
    alias: str
    model_used: str | None
    in_tokens: int
    out_tokens: int
    latency_ms: int
    status: int
    cache_hit: bool
    fallback_used: bool
    cache_status: str | None = None
    cache_scope: str | None = None
    coalesce_role: str | None = None
    queue_wait_ms: int | None = None
    ttft_ms: int | None = None
    tags: dict[str, str] | None = None


class LogPage(BaseModel):
    items: list[LogOut]
    next_cursor: int | None = Field(description="Pass as ?before= to fetch the next (older) page.")


class AliasOut(BaseModel):
    id: str
    chain: list[str] = Field(description="Upstream models in fallback order")
    terse: bool


class UserLimits(BaseModel):
    max_keys: int
    max_rpm: int
    max_daily_tokens: int


class Me(BaseModel):
    owner_id: str | None = Field(description="None for the operator (ADMIN_TOKEN only)")
    active_keys: int
    limits: UserLimits | None = Field(description="Self-serve caps; None for the operator")


class CoalesceStats(BaseModel):
    window_hours: int
    leaders: int = Field(description="Requests that made the upstream call for a group")
    followers: int = Field(description="Requests served from another request's upstream call")
    calls_saved: int
    share_rate: float = Field(description="followers / (leaders + followers)")
    in_flight: int = Field(description="Coalescable upstream calls running now")
    largest_fanout_since_start: int
    flights_since_start: int
