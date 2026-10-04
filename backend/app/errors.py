"""OpenAI-style error envelopes: {"error": {"type", "message"}} for every failure."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging_setup import request_id_var

log = logging.getLogger("tollgate.errors")

# Infrastructure failures reported as 503 service_unavailable.
DEPENDENCY_ERRORS: tuple[type[Exception], ...] = (RedisError, SQLAlchemyError, OSError)

_TYPE_BY_STATUS = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found",
    422: "invalid_request_error",
    429: "rate_limit",
}


class GatewayError(Exception):
    """Raise anywhere on the request path to return a typed error envelope."""

    def __init__(
        self,
        status_code: int,
        type_: str,
        message: str,
        *,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.type = type_
        self.message = message
        self.code = code
        self.headers = headers


def error_response(
    status_code: int,
    type_: str,
    message: str,
    *,
    code: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    error: dict[str, str] = {"type": type_, "message": message}
    if code:
        error["code"] = code
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(GatewayError)
    async def _gateway(_: Request, exc: GatewayError) -> JSONResponse:
        return error_response(exc.status_code, exc.type, exc.message, code=exc.code, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        type_ = _TYPE_BY_STATUS.get(exc.status_code, "server_error" if exc.status_code >= 500 else "error")
        return error_response(exc.status_code, type_, str(exc.detail), headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        message = f"{loc}: {first.get('msg', 'invalid request')}" if loc else first.get("msg", "invalid request")
        return error_response(422, "invalid_request_error", message)

    async def _dependency_down(_: Request, exc: Exception) -> JSONResponse:
        log.error("dependency unavailable", extra={"error": repr(exc)})
        return error_response(503, "service_unavailable", "A gateway dependency is unavailable; retry shortly.")

    for exc_type in DEPENDENCY_ERRORS:
        app.add_exception_handler(exc_type, _dependency_down)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return error_response(500, "server_error", f"internal error (request_id={request_id_var.get()})")
