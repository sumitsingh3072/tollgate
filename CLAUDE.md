# Tollgate Lite

OpenAI-compatible LLM gateway (FastAPI + Redis + Neon Postgres) in front of local Ollama models.
Adds API keys, rate limits, token quotas, caching, fallback, terse mode, logging, and a Next.js dashboard.

**Source of truth:** `docs/plan.md`, `docs/architecture.md`, `docs/phase.md`. Read all three before any work.

## Golden rule
Nothing slow on the request path. Key lookups hit Redis first (60s TTL). DB writes go through an
in-memory queue, flushed in batches every 2 seconds.

## Run
```
docker compose up -d                              # repo root: redis
cd backend && uvicorn app.main:app --reload --port 8000
cd backend && python mock_upstream.py             # :9000, always 500
cd frontend && pnpm dev                           # :3000
cd backend && pytest
```

## Conventions
- Async everywhere; type hints on all functions.
- Reuse `app.state.http` (one shared httpx.AsyncClient); never create per-request clients.
- Small, focused modules matching the layout in docs/architecture.md.
- Any code that calls an upstream gets tests using respx.
- Frontend is Next.js 16 (async `params`, `RouteContext`, Tailwind v4). Check `frontend/node_modules/next/dist/docs/` before using Next APIs.

## Workflow
- Work one phase at a time (docs/phase.md).
- Tick tasks `[x]` in docs/phase.md as they are completed.
- Stop for review when the phase's "Done when" passes.
