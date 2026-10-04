# Tollgate Lite

OpenAI-compatible LLM gateway (FastAPI + Redis + Neon Postgres) in front of Google's Gemma 4 models
(served by the Gemini API's OpenAI-compatible endpoint).
Adds API keys, rate limits, token quotas, caching, fallback, terse mode, logging, and a Next.js dashboard.

**Source of truth:** `docs/plan.md`, `docs/architecture.md`, `docs/phase.md`. Read all three before any work.

## Golden rule
Nothing slow on the request path. Key lookups hit Redis first (60s TTL). DB writes go through an
in-memory queue, flushed in batches every 2 seconds.

## Run
```
cp .env.example .env                              # fill GEMINI_API_KEY, DATABASE_URL, ADMIN_TOKEN
docker compose up -d --build                      # full stack (add --profile localdb for local Postgres)
docker compose up -d redis                        # infra only, for host dev
cd backend && uv venv -p 3.12 .venv && uv pip install -r requirements-dev.txt
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
cd backend && .venv/bin/python mock_upstream.py   # :9000, always 500
cd backend && .venv/bin/python scripts/smoke_openai.py --model fast   # SDK end-to-end
cd frontend && cp .env.example .env.local && pnpm dev   # :3000
cd backend && .venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/ruff format --check .
cd frontend && pnpm lint && pnpm build
```

## Conventions
- Async everywhere; type hints on all functions.
- Reuse `app.state.http` (one shared httpx.AsyncClient); never create per-request clients.
- Small, focused modules matching the layout in docs/architecture.md.
- Any code that calls an upstream gets tests using respx.
- Log via `logging.getLogger("tollgate.<module>")` with `extra={...}` fields; never log secrets or prompts.
- Raise `GatewayError` for client-facing failures; responses use the OpenAI error envelope.
- Secrets are `SecretStr`; the Gemini key lives only in the backend, ADMIN_TOKEN only server-side in Next.
- Frontend: shadcn components (base-nova, Base UI `render` prop, not `asChild`), theme tokens from
  `app/globals.css` (no hard-coded colors), Linear-style density; verify light and dark.
- Frontend is Next.js 16 (async `params`, `RouteContext`, Tailwind v4). Check `frontend/node_modules/next/dist/docs/` before using Next APIs.

## Workflow
- Work one phase at a time (docs/phase.md).
- Tick tasks `[x]` in docs/phase.md as they are completed.
- Stop for review when the phase's "Done when" passes.
