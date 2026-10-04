"""OpenAI-compatible request/response shapes. Unknown fields are allowed and forwarded unchanged."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
