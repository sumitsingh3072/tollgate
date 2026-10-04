# Tollgate Lite: Plan

## What it is
An OpenAI-compatible LLM gateway. Apps change one line (their SDK base_url) and
every request flows through Tollgate, which adds API keys, rate limits, daily
token quotas, exact-match caching, model fallback with a circuit breaker,
streaming passthrough, a "terse mode" that reduces output tokens, and request
logging with analytics. Models are open source, served locally by Ollama
(OpenAI-compatible at http://localhost:11434/v1), so no provider adapters needed.

## Who uses it
- Developer: swaps base_url to http://localhost:8000/v1 and uses a Tollgate key.
  Works with the OpenAI SDK, Open WebUI, Continue, n8n.
- Admin / team lead: uses the Next.js dashboard to create and revoke keys, watch
  usage, cache hits, latency and failovers, and test in the Playground.

## Model aliases (the "model" field acts like a mode switch)
| Alias        | Chain (in order)                 | Notes                 |
|--------------|----------------------------------|-----------------------|
| fast         | qwen2.5:1.5b                     | quick, small          |
| smart        | llama3.2:3b -> qwen2.5:1.5b      | fallback on failure   |
| smart-terse  | same as smart                    | injects terse prompt  |

## Stack
- Backend: Python 3.12, FastAPI, uvicorn, httpx (async, one pooled client),
  SQLAlchemy 2.0 async + asyncpg, redis-py asyncio, pydantic-settings
- Database: Neon Postgres (DATABASE_URL)
- Hot path: Redis (docker-compose)
- Frontend: Next.js 16 App Router, TypeScript, Tailwind v4, shadcn/ui, Recharts
- Tests: pytest-asyncio, respx

## In scope
Streaming proxy, hashed API keys, per-key RPM limit, daily token quota, exact
cache (temperature 0, non-streaming), fallback chain, circuit breaker, terse
mode, batched logging to Neon, stats with p50/p95, dashboard (Overview, Keys,
Logs, Playground), mock failing upstream for demos.

## Out of scope
Multiple orgs/projects, dollar pricing, semantic cache, OpenTelemetry/Grafana,
prompt library, alerts, Alembic migrations, user login (single ADMIN_TOKEN).

## Golden rule
Nothing slow on the request path. Key lookups hit Redis first (60s TTL). DB
writes go through an in-memory queue, flushed in batches every 2 seconds.

## Success criteria
- OpenAI Python SDK works by changing only base_url, streaming included.
- One key hits its limit while another keeps working.
- Mock 500 upstream fails over to the next model without client errors.
- Cache hits return in a few ms with x-tollgate-cache: hit.
- README shows a terse vs normal token benchmark on 20 prompts.
