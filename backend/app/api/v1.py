"""OpenAI-compatible data plane: /v1/chat/completions, /v1/models. Phase 1."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["v1"])
