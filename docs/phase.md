# Tollgate Lite: Phases

Mark tasks [x] as they are completed. One phase per session. Do not start
the next phase until "Done when" passes. Every phase keeps `ruff check`,
`pytest`, `pnpm lint` and `pnpm build` green.

## Phase 0: Setup and foundation
- [x] Create folder structure from architecture.md with stub modules (docstrings only)
- [x] backend requirements.txt with pinned versions
- [x] config.py Settings + aliases; db/models.py tables; create_all on startup
- [x] main.py lifespan: shared httpx.AsyncClient, redis client, db engine
- [x] GET /health with redis + db checks; tests/test_health.py
- [x] mock_upstream.py (FastAPI on :9000, always 500)
- [x] frontend: create-next-app (TS, Tailwind, App Router), shadcn init,
      sidebar layout, placeholder pages, admin proxy route, .env.example
- [x] Switch upstream from Ollama to Gemma 4 on the Gemini API (OpenAI-compatible endpoint);
      Upstream carries api_key (hidden from repr); model IDs env-configurable
- [x] Single root .env.example shared by compose and the local backend
      (GEMINI_API_KEY, DATABASE_URL, REDIS_URL, ADMIN_TOKEN, CORS_ORIGINS, LOG_*)
- [x] Structured logging (console / JSON), request-id middleware, access log,
      OpenAI-style error envelopes for 404/422/500, startup warnings for
      default ADMIN_TOKEN / missing GEMINI_API_KEY
- [x] /health checks run concurrently with a timeout
- [x] requirements-dev.txt, pyproject.toml (ruff + pytest), tests for config,
      middleware and errors
- [x] Dockerfiles (backend + mock, frontend standalone), non-root, healthchecks;
      docker compose for the full stack, optional local Postgres profile,
      overridable host ports
- [x] Dashboard shell: Linear-inspired tokens (light + dark), Inter, shadcn
      sidebar (inset, collapsible to icons, ⌘B), header, theme toggle
      (light/dark/system, no flash), live gateway status, empty-state pages
Done when: pytest + ruff pass, `pnpm lint && pnpm build` pass,
`docker compose --profile localdb up -d --build` reports all services healthy
and /health shows redis and db true.

## Phase 1: Streaming proxy (Gemma via Gemini API)
- [x] POST /v1/chat/completions forwards to the first model in the alias chain
      (Bearer upstream.api_key, model rewritten to the Gemma model id)
- [x] Request schema: validate messages/model, pass unknown OpenAI fields through
- [x] stream=true relays SSE chunks via StreamingResponse; request
      stream_options.include_usage
- [x] Upstream 4xx/5xx mapped to the OpenAI error envelope (incl. Gemini's
      list-shaped errors); unknown alias -> 404 model_not_found
- [x] GET /v1/models lists aliases (OpenAI list shape); GET /v1/models/{id}
- [x] Log one line per upstream call (alias, model, status, latency_ms)
- [x] respx tests: non-stream, stream chunk-by-chunk, upstream error mapping
- [x] Gemma thinking off by default (GEMINI_THINKING_LEVEL=minimal) so no
      <thought> text leaks into content; client extra_body overrides
- [x] scripts/smoke_openai.py: OpenAI SDK end-to-end check
Done when: OpenAI Python SDK works with only base_url changed, streaming included.

## Phase 2: Keys and limits
- [ ] POST/GET/DELETE /admin/keys; tg_live_ + 32 random chars; store SHA-256 only
- [ ] Admin-token dependency (constant-time compare)
- [ ] Auth dependency with Redis-cached lookup (60s TTL); revoke deletes cache entry
- [ ] RPM limit and daily token quota in Redis; 429 with clear JSON + Retry-After
Done when: hammering one key hits its limit while a second key still works.

## Phase 3: Cache, failover, terse
- [ ] Exact cache for temperature 0 non-streaming, TTL 1h
- [ ] Fallback through the chain on connect error, timeout, 5xx
- [ ] Circuit breaker: 3 failures -> open 30s
- [ ] demo-failover alias: mock upstream -> fast Gemma model
- [ ] Terse mode system-prompt injection for *-terse aliases
- [ ] Response headers x-tollgate-model / -cache / -fallback
Done when: demo-failover fails over cleanly and a repeated request returns
cache: hit.

## Phase 4: Logging and analytics
- [ ] asyncio queue + background flusher, batch insert every 2s; drain on shutdown
- [ ] GET /admin/stats: totals, tokens by key, cache hit rate, error rate, p50/p95
- [ ] GET /admin/logs: pagination + filters
Done when: stats reflect requests just made; no DB call on the request path.

## Phase 5: Dashboard (shadcn, Linear-style, light + dark)
- [ ] Shared: loading skeletons, error + empty states, toasts (sonner)
- [ ] Overview: stat cards + tokens-by-key bar chart (Recharts, theme-aware colors)
- [ ] Keys: create dialog (show key once, copy button), table, revoke confirm
- [ ] Logs: table with status/cache/fallback badges, filters, pagination
- [ ] Playground: alias picker, streaming output, shows response headers
- [ ] Command menu (⌘K) for navigation
Done when: create key -> chat in Playground -> see it in Logs and Overview,
in both light and dark themes.

## Phase 6: Hardening and ship
- [ ] GitHub Actions CI: ruff, pytest, pnpm lint + build, docker build
- [ ] README: pitch, Mermaid diagram, quickstart (docker + local), SDK + Open WebUI examples
- [ ] Benchmark script: 20 prompts on smart vs smart-terse; results table
- [ ] Demo recording: stream, cache hit, 429, failover
Done when: a stranger can run it from the README in under 10 minutes.

Cut order if late: command menu -> circuit breaker -> terse mode -> Overview charts.
