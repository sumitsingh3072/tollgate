"""Mock upstream on :9000 that always returns 500. Used to demo failover."""

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Tollgate mock upstream")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def always_fail(path: str) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": {"type": "server_error", "message": f"mock upstream failure on /{path}"}},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
