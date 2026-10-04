# Tollgate Lite: Plan

## What it is
An OpenAI-compatible LLM gateway. Apps change one line (their SDK base_url) and
every request flows through Tollgate, which adds API keys, rate limits, daily
token quotas, exact-match caching, model fallback with a circuit breaker,
streaming passthrough, a "terse mode" that reduces output tokens, and request
logging with analytics. Upstream models are Google's open Gemma 4 models, served
by the Gemini API and reached through
Gemini's OpenAI-compatible endpoint
(https://generativelanguage.googleapis.com/v1beta/openai, Bearer GEMINI_API_KEY),
so no provider adapters are needed. Any other OpenAI-compatible upstream can be
added to an alias chain the same way.

## Who uses it
- Developer: swaps base_url to http://localhost:8000/v1 and uses a Tollgate key.
  Works with the OpenAI SDK, Open WebUI, Continue, n8n.
- Admin / team lead: uses the Next.js dashboard to create and revoke keys, watch
  usage, cache hits, latency and failovers, and test in the Playground.

## Model aliases (the "model" field acts like a mode switch)
| Alias          | Chain (in order)                            | Notes                    |
|----------------|---------------------------------------------|--------------------------|
| fast           | gemma-4-26b-a4b-it                          | MoE, 4B active, quick    |
| smart          | gemma-4-31b-it -> gemma-4-26b-a4b-it        | fallback on failure      |
| smart-terse    | same as smart                               | injects terse prompt     |
| demo-failover  | mock upstream (500) -> gemma-4-26b-a4b-it   | Phase 3, failover demo   |

Model IDs are env-configurable (GEMINI_FAST_MODEL, GEMINI_SMART_MODEL).

## Stack
- Backend: Python 3.12, FastAPI, uvicorn, httpx (async, one pooled client),
  SQLAlchemy 2.0 async + asyncpg, redis-py asyncio, pydantic-settings
- Upstream: Gemma 4 via the Gemini API's OpenAI-compatible endpoint (GEMINI_API_KEY)
- Database: Neon Postgres (DATABASE_URL); optional local Postgres via compose profile
- Hot path: Redis
- Frontend: Next.js 16 App Router, TypeScript, Tailwind v4, shadcn/ui (Base UI
  primitives), Recharts. Linear-inspired look: dense type (Inter, 13px),
  near-black / near-white chrome, indigo accent, hairline borders, inset content
  panel. Light, dark and system themes, no flash on load.
- Containers: Docker images for backend, mock upstream and dashboard;
  docker compose runs the whole stack
- Observability: structured logs (console or JSON lines), x-request-id on every
  response and log line, one access log per request
- Tooling: ruff (lint + format), pytest-asyncio, respx; ESLint, TypeScript strict

## In scope
Streaming proxy, hashed API keys, per-key RPM limit, daily token quota, exact
cache (temperature 0, non-streaming), fallback chain, circuit breaker, terse
mode, batched logging to Neon, stats with p50/p95, dashboard (Overview, Keys,
Logs, Playground), mock failing upstream for demos.

## Out of scope
Multiple orgs/projects, dollar pricing, semantic cache, OpenTelemetry/Grafana,
prompt library, alerts, Alembic migrations, user login (single ADMIN_TOKEN),
non-chat endpoints (embeddings, images).

## Golden rule
Nothing slow on the request path. Key lookups hit Redis first (60s TTL). DB
writes go through an in-memory queue, flushed in batches every 2 seconds.

## Success criteria
- OpenAI Python SDK works by changing only base_url, streaming included.
- One key hits its limit while another keeps working.
- Mock 500 upstream fails over to the next model without client errors.
- Cache hits return in a few ms with x-tollgate-cache: hit.
- README shows a terse vs normal token benchmark on 20 prompts.
- `docker compose up -d --build` brings up the whole stack with only .env filled in.
