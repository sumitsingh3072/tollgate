"""OpenAI-compatible data plane: /v1/chat/completions, /v1/models."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import Alias
from app.core import proxy
from app.errors import GatewayError
from app.schemas import ChatCompletionRequest, ModelCard, ModelList

router = APIRouter(prefix="/v1", tags=["v1"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _resolve_alias(request: Request, name: str) -> Alias:
    aliases: dict[str, Alias] = request.app.state.aliases
    alias = aliases.get(name)
    if alias is None:
        raise GatewayError(
            404,
            "invalid_request_error",
            f"model '{name}' not found; available: {', '.join(aliases)}",
            code="model_not_found",
        )
    return alias


@router.post("/chat/completions", response_model=None)
async def chat_completions(body: ChatCompletionRequest, request: Request) -> JSONResponse | StreamingResponse:
    alias = _resolve_alias(request, body.model)
    upstream = alias.chain[0]  # Phase 3 walks the full chain with fallback.
    payload = proxy.build_payload(body.upstream_body(), upstream)
    http = request.app.state.http

    if body.stream:
        chunks = await proxy.open_stream(http, body.model, upstream, payload)
        return StreamingResponse(chunks, media_type="text/event-stream", headers=SSE_HEADERS)
    # Upstream JSON is already OpenAI-shaped; skip FastAPI's re-encoding pass.
    return JSONResponse(await proxy.complete(http, body.model, upstream, payload))


@router.get("/models")
async def list_models(request: Request) -> ModelList:
    return ModelList(data=[ModelCard(id=name) for name in request.app.state.aliases])


@router.get("/models/{model_id}")
async def get_model(model_id: str, request: Request) -> ModelCard:
    _resolve_alias(request, model_id)
    return ModelCard(id=model_id)
