# Tollgate Lite: Phases (5 hours total)

Mark tasks [x] as they are completed. One phase per session. Do not start
the next phase until "Done when" passes.

## Phase 0: Setup (0:00-0:30)
- [x] Create folder structure from architecture.md with stub modules (docstrings only)
- [x] backend requirements.txt with pinned versions; .env.example
      (DATABASE_URL, REDIS_URL, OLLAMA_BASE_URL, ADMIN_TOKEN, KEY_CACHE_TTL=60,
      LOG_FLUSH_INTERVAL=2)
- [x] config.py Settings + MODEL_ALIASES; db/models.py tables; create_all on startup
- [x] main.py lifespan: shared httpx.AsyncClient, redis client, db engine
- [x] GET /health with redis + db checks; tests/test_health.py
- [x] mock_upstream.py (FastAPI on :9000, always 500)
- [x] docker-compose.yml with redis:7
- [x] frontend: create-next-app (TS, Tailwind, App Router), shadcn init,
      sidebar layout, placeholder pages, admin proxy route, .env.example
Done when: pytest passes, /health shows redis and db true, `pnpm build` passes.

## Phase 1: Streaming proxy (0:30-1:20)
- [ ] POST /v1/chat/completions forwards to the first model in the alias chain
- [ ] stream=true relays SSE chunks via StreamingResponse
- [ ] GET /v1/models lists aliases
- [ ] respx tests: non-stream and stream chunk-by-chunk
Done when: OpenAI Python SDK works with only base_url changed, streaming included.

## Phase 2: Keys and limits (1:20-2:00)
- [ ] POST/GET/DELETE /admin/keys; tg_live_ + 32 random chars; store SHA-256 only
- [ ] Auth dependency with Redis-cached lookup (60s TTL); revoke deletes cache entry
- [ ] RPM limit and daily token quota in Redis; 429 with clear JSON
Done when: hammering one key hits its limit while a second key still works.

## Phase 3: Cache, failover, terse (2:00-2:50)
- [ ] Exact cache for temperature 0 non-streaming, TTL 1h
- [ ] Fallback through the chain on connect error, timeout, 5xx
- [ ] Circuit breaker: 3 failures -> open 30s
- [ ] Terse mode system-prompt injection for *-terse aliases
- [ ] Response headers x-tollgate-model / -cache / -fallback
Done when: a chain starting with the mock upstream fails over cleanly and a
repeated request returns cache: hit.

## Phase 4: Logging and analytics (2:50-3:20)
- [ ] asyncio queue + background flusher, batch insert every 2s
- [ ] GET /admin/stats: totals, tokens by key, cache hit rate, error rate, p50/p95
- [ ] GET /admin/logs: pagination + filters
Done when: stats reflect requests just made; no DB call on the request path.

## Phase 5: Dashboard (3:20-4:30)
- [ ] Overview: stat cards + tokens-by-key bar chart (Recharts)
- [ ] Keys: create dialog (show key once, copy button), list, revoke
- [ ] Logs: table with status/cache/fallback badges
- [ ] Playground: alias picker, streaming output, shows response headers
Done when: create key -> chat in Playground -> see it in Logs and Overview.

## Phase 6: Ship (4:30-5:00)
- [ ] README: pitch, Mermaid diagram, quickstart, SDK + Open WebUI examples
- [ ] Benchmark script: 20 prompts on smart vs smart-terse; results table
- [ ] Demo recording: stream, cache hit, 429, failover
Done when: a stranger can run it from the README in under 10 minutes.

Cut order if late: circuit breaker -> terse mode -> Overview charts.
