# Tollgate Lite

OpenAI-compatible LLM gateway in front of Google's open Gemma 4 models (via the Gemini API). Change one line (`base_url`) and every
request gets API keys, rate limits, daily token quotas, exact-match caching, model fallback with a
circuit breaker, streaming passthrough, terse mode, and request analytics in a Linear-style dashboard.

> Work in progress. See [docs/phase.md](docs/phase.md) for status; full README lands in Phase 6.

## Quickstart (Docker)

```bash
cp .env.example .env        # set GEMINI_API_KEY, ADMIN_TOKEN, DATABASE_URL (Neon), Clerk keys
docker compose up -d --build
# no Neon? use local Postgres:
#   DATABASE_URL=postgresql://tollgate:tollgate@postgres:5432/tollgate
#   docker compose --profile localdb up -d --build
```

- Gateway: http://localhost:8000 (`/health`, `/docs`)
- Landing + dashboard: http://localhost:3000 (sign in with Clerk; the dashboard is at /dashboard)
- Mock failing upstream: http://localhost:9000

Port already taken? Override host ports, e.g. `REDIS_PORT=6380 docker compose up -d`.

## Local development

See [CLAUDE.md](CLAUDE.md#run) for host-run commands. Docs: [plan](docs/plan.md),
[architecture](docs/architecture.md), [phases](docs/phase.md).
