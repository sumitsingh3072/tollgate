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


class ModelUsage(BaseModel):
    model: str | None
    requests: int
    tokens: int


class Stats(BaseModel):
    window_hours: int
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
    by_key: list[KeyUsage]
    by_model: list[ModelUsage]


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


class LogPage(BaseModel):
    items: list[LogOut]
    next_cursor: int | None = Field(description="Pass as ?before= to fetch the next (older) page.")
