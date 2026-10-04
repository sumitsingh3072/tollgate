"""Mock OpenAI-compatible upstream on :9000 that always fails (default 500). Used to demo failover.

MOCK_STATUS overrides the status code, e.g. MOCK_STATUS=503.
"""

import logging
import os

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

STATUS = int(os.getenv("MOCK_STATUS", "500"))
log = logging.getLogger("tollgate.mock")

app = FastAPI(title="Tollgate mock upstream", docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def always_fail(path: str) -> JSONResponse:
    log.info("mock failure", extra={"path": f"/{path}", "status": STATUS})
    return JSONResponse(
        status_code=STATUS,
        content={"error": {"type": "server_error", "message": f"mock upstream failure on /{path}"}},
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "9000")))
