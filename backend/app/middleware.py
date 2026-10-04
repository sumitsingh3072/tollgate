"""Pure-ASGI request context middleware (safe for streaming responses).

Assigns/propagates x-request-id and writes one access log line when the response finishes.
"""

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.logging_setup import request_id_var

access_log = logging.getLogger("tollgate.access")

REQUEST_ID_HEADER = b"x-request-id"
_SKIP_ACCESS_LOG = frozenset({"/health", "/health/live"})
# Accept a caller-supplied id only if it is short and log-safe.
_VALID_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER, b"").decode("latin-1")
        request_id = incoming if _VALID_ID.fullmatch(incoming) else uuid.uuid4().hex
        # Each request runs in its own task context, so no reset is needed; keeping the id set
        # also lets the outermost 500 handler report it.
        request_id_var.set(request_id)
        start = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((REQUEST_ID_HEADER, request_id.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope["path"]
            if path not in _SKIP_ACCESS_LOG:
                access_log.info(
                    "%s %s %d",
                    scope["method"],
                    path,
                    status,
                    extra={"status": status, "latency_ms": round((time.perf_counter() - start) * 1000, 1)},
                )
