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
- [x] POST/GET/DELETE /admin/keys; tg_live_ + 32 random chars; store SHA-256 only
      (list includes tokens_today; revoke is idempotent)
- [x] Admin-token dependency (constant-time compare)
- [x] Auth dependency with Redis-cached lookup (60s TTL); revoke deletes cache entry;
      unknown/revoked keys negatively cached so bad keys never hammer the DB
- [x] RPM limit and daily token quota in Redis (one round trip); 429 with clear JSON
      + Retry-After; x-ratelimit-* headers on success
- [x] Token accounting: usage.total_tokens (includes Gemma thinking tokens), parsed
      from streams too, chars/4 estimate when upstream omits usage
- [x] Redis/DB outages return 503 service_unavailable; tests on fakeredis + SQLite
Done when: hammering one key hits its limit while a second key still works.

## Phase 3: Cache, failover, terse
- [x] Exact cache for temperature 0 non-streaming, TTL 1h (key = sha256 of the
      canonical body, so tools/response_format etc. never collide; hits not billed)
- [x] Fallback through the chain on connect error, timeout, 5xx (and upstream 429);
      streams fall back until the first byte
- [x] Circuit breaker: 3 failures -> open 30s, then half-open trial
- [x] demo-failover alias: mock upstream -> fast Gemma model
- [x] Terse mode system-prompt injection for *-terse aliases (merged into an
      existing system message)
- [x] Response headers x-tollgate-model / -cache (hit|miss|bypass) / -fallback
Done when: demo-failover fails over cleanly and a repeated request returns
cache: hit.

## Phase 4: Logging and analytics
- [x] In-memory buffer + background flusher, batch insert every 2s; final flush on
      shutdown; failed batches retried; buffer capped (drops, never blocks)
- [x] One log event per authenticated request: success, cache hit, 4xx/5xx/429,
      and streams (logged when the stream ends)
- [x] GET /admin/stats?hours=: totals, tokens by key and by model, cache hit rate,
      error rate, p50/p95 (percentile_cont)
- [x] GET /admin/logs: keyset pagination (before/next_cursor) + filters (key_id,
      alias, status, errors_only)
Done when: stats reflect requests just made; no DB call on the request path.

## Phase 5: Dashboard (shadcn, Linear-style, light + dark)
- [x] Shared: loading skeletons (Suspense), error boundary + empty states, 404, toasts (sonner)
- [x] Overview: stat cards + tokens-by-key and requests-by-model charts (Recharts via
      shadcn chart, theme tokens), 24h / 7d / 30d window
- [x] Keys: create dialog (show key once, copy button), table with quota bars, revoke confirm
- [x] Logs: table with status/cache/fallback badges, URL-driven filters, keyset pagination
- [x] Playground: alias picker (with chain), multi-turn streaming chat, stop, response
      headers + timing + usage panel; key kept in sessionStorage
- [x] Command menu (⌘K) for navigation and theme
- [x] Richer Overview: stat tiles with delta vs previous window + sparkline, traffic
      chart (requests / tokens / latency), GitHub-style yearly activity heatmap,
      status mix, latency histogram, model and alias breakdown tables; chart palette
      validated for both themes (dataviz validator)
- [x] scripts/seed_demo.py: a year of synthetic traffic for demos (explicit DB URL only)
- [x] Backend: GET /admin/aliases; CORS exposes x-ratelimit-* / retry-after
Done when: create key -> chat in Playground -> see it in Logs and Overview,
in both light and dark themes.

## Phase 6: Accounts (Clerk) and landing page
- [x] Public landing page at / (hero with real product shot, numbers, features, how it
      works, quickstart code tabs, CTA); dashboard moves under /dashboard/* via route
      groups ((marketing) and (app))
- [x] Clerk (@clerk/nextjs 7): own /sign-in and /sign-up pages themed with our tokens
      (--clerk-* vars), UserButton in the header; auth checked where data is read
      ((app)/layout auth.protect + every admin call), not by path matching
- [x] Backend ownership: api_keys.owner_id (Clerk user id) with an idempotent
      ADD COLUMN IF NOT EXISTS at startup (no Alembic); keys, stats, activity and logs
      scoped to the owner
- [x] Trust model: dashboard server calls /admin with ADMIN_TOKEN + X-Tollgate-User
      (from Clerk auth()); ADMIN_TOKEN alone keeps a full operator view
- [x] Abuse/cost guards (shared GEMINI_API_KEY): max keys per user, max rpm and
      daily quota per key for self-serve users (env-configurable); GET /admin/me
- [x] Tests: ownership isolation (user A cannot see/revoke user B's keys or logs)
- [x] Docker: Clerk publishable key baked in at build, secret key at runtime
Done when: two different sign-ins each create keys and only see their own keys,
logs and stats; signed-out visitors see the landing page and get redirected from
/dashboard.

## Phase 7: Easy self-hosting (API by default, local optional)
- [x] Provider switch: UPSTREAM_PROVIDER=gemini (default, light on the machine) | ollama
      (local; gemma3:1b / gemma3:4b by default)
- [x] docker compose with only GEMINI_API_KEY set: bundled Postgres, Redis, generated
      admin token (secrets-init) shared by gateway and dashboard via ADMIN_TOKEN_FILE;
      `--profile ollama` adds Ollama + a one-shot model pull into a volume
- [x] Accounts optional: no Clerk keys = local mode (no sign-in, operator view);
      Clerk keys = public multi-user mode
- [x] Remote-ready: BIND_ADDRESS (localhost by default), NEXT_PUBLIC_GATEWAY_URL,
      CORS_ORIGINS; infra ports unpublished by default (compose.dev.yml for host dev),
      compose.gpu.yml for NVIDIA
- [x] /health reports whether the provider is usable (Gemini key set / Ollama models
      pulled); sidebar shows it
Done when: a clean copy with only GEMINI_API_KEY in .env comes up with
`docker compose up -d`, the dashboard opens without sign-in, and a chat is answered.

## Phase 8: Advanced features, quick wins (cache core + visibility core)
Spec: "Every token pays the toll": avoid repeated work, share capacity fairly, prove it.
- [x] Separate response-cache Redis (allkeys-lfu, maxmemory, lfu-decay) from the state Redis
      (noeviction), so cache pressure can never evict limits or quotas
- [x] Eligibility: temperature 0 (or route opt-in), no tools/n>1; store only finish_reason
      "stop", no tool calls, <= CACHE_MAX_ENTRY_BYTES
- [x] Canonical key sha256(scope | alias | canonical request) with normalized message text;
      private scope (API key id) by default
- [x] Admission on second sight (simplified TinyLFU): "seen:" marker first, store on repeat
- [x] Per-route TTL (default 24h); x-tollgate-cache = hit | miss | admission_rejected |
      ineligible | bypass
- [x] request_logs: cache_status, cache_scope, coalesce_role, queue_wait_ms, ttft_ms, tags
      (idempotent migrations); x-tollgate-tags header; log filters by cache_status / tag
- [x] /metrics (Prometheus, admin token): GenAI token usage, duration, TTFT; cache counters
- [x] /health/live liveness endpoint (container healthcheck) separate from /health readiness

## Phase 9: Request coalescing
- [x] Flight registry keyed by the cache key (+ json/sse); leader runs upstream as its own task,
      followers replay buffered chunks then wait; late joiners get the full response
- [x] Cancellation safety (cancel upstream only when subscribers == 0), shared errors; every
      upstream call runs in a Flight (private ones for non-coalescable requests)
- [x] Billing per receiving key; coalesce_role logged; x-tollgate-coalesce header; admit to cache
      immediately when >= 2 followers; COALESCING_ENABLED toggle (benchmarks)
- [x] Metrics tollgate_coalesced_requests_total{role}; /admin/coalesce/stats

## Phase 10: Fair queuing (VTC)
- [x] Gateway-owned concurrency per upstream model (UPSTREAM_MAX_PARALLEL; Ollama's
      OLLAMA_NUM_PARALLEL follows it) so the provider's own queue stays empty
- [x] Virtual Token Counter per key (input + 2 x output, charged at dispatch and while streaming),
      lowest counter dispatches first, counter lift for newly active keys; only coalescing
      leaders take slots. (Per-key weights: supported by the scheduler, not exposed yet.)
- [x] Backpressure: FAIR_MAX_QUEUE_PER_KEY (queue_full), FAIR_MAX_WAIT_S (queue_timeout) -> 429
      + Retry-After; x-tollgate-queue-wait-ms; tollgate_queue_depth / tollgate_queue_wait_seconds;
      /admin/fairness (tokens, share, wait p95, live depth, VTC counters, Jain's index)
- [x] FAIR_QUEUE_MODE=fair|fifo|off for benchmarking

## Phase 11: Shared cache, stream caching, dashboard pages, benchmarks
- [x] Shared scope (opt-in, "faq" alias) with per-key insert budgets; cache/coalesce headers hidden
- [x] Cache streamed responses (rebuilt into one completion) and replay hits as SSE or JSON
- [x] /admin/cache/stats (hit rate, memory vs limit, evictions, rejections, entries, hits per MB)
- [x] Dashboard: Cache and Fairness (live) pages; Overview TTFT and "model calls saved" tiles;
      Logs show coalescing and queue wait
- [x] bench/: in-process harness with a simulated model, Zipf + one-off workload, cache_bench,
      coalesce_bench, fair_bench; measured results in docs/benchmarks.md
- [x] Fix found by the benchmarks: gateway queue rejections no longer count as upstream failures
      (circuit breaker), and the fallback deadline covers the upstream call, not queue waiting

## Phase 12: Hardening and ship
- [ ] GitHub Actions CI: ruff, pytest, pnpm lint + build, docker build
- [ ] README: pitch, Mermaid diagram, quickstart (docker + local), SDK + Open WebUI examples
- [ ] Benchmark script: 20 prompts on smart vs smart-terse; results table
- [ ] Demo recording: stream, cache hit, 429, failover
Done when: a stranger can run it from the README in under 10 minutes.

Cut order if late: command menu -> circuit breaker -> terse mode -> Overview charts.
Phase 6 is optional for a single-team deployment (ADMIN_TOKEN-only mode keeps working).
