# Benchmarks

All numbers below were measured, not predicted, on a MacBook (Apple Silicon) with the scripts in
`backend/bench/`. They run the real gateway app in-process against a **simulated model** (an
in-memory upstream with a FIFO "GPU" and per-token latency), so they are reproducible, free and need
no API key. The cache benchmark uses a real Redis, since memory and evictions are what it measures.
Raw results: `backend/bench/results/*.json`.

```bash
cd backend
python -m bench.coalesce_bench
python -m bench.fair_bench
docker compose -f ../docker-compose.yml -f ../compose.dev.yml up -d redis redis-cache
python -m bench.cache_bench --redis-url redis://localhost:6379/0 --cache-url redis://localhost:6381/0
```

## Request coalescing

50 identical requests arrive at once; each model call takes 0.5 s; 4 model slots.

| coalescing | upstream calls | clients served | total time |
|---|---|---|---|
| off | 50 | 50 | 6.61 s |
| on  | **1** | 50 | **0.56 s** |

One model call answered all 50 clients. With coalescing off the 50 calls queue for 4 slots.

## Fair queuing (VTC)

A heavy client keeps 20 long requests (400 output tokens) in flight; a light client sends one short
request (20 tokens) every 2 s; the model has one slot; 20 s per run.

| queue | light p50 | light p95 | light requests done | Jain's index (tokens) |
|---|---|---|---|---|
| none (model server FIFO) | 8.03 s | 8.12 s | 2 | 0.50 |
| gateway FIFO | 8.02 s | 8.10 s | 2 | 0.50 |
| gateway fair (VTC) | **0.10 s** | **0.20 s** | **10** | 0.51 |

Under FIFO the light client waits behind the heavy client's whole backlog; with VTC it goes next,
because its virtual token counter is far lower. Heavy throughput was identical in all three runs
(27,336 tokens): fairness reorders work, it does not waste the model.

Jain's index over *raw tokens* stays near 0.5 in every run. That is expected: the heavy client asks
for 20x more tokens per request and is always backlogged, while the light client is not. VTC
equalizes service between *backlogged* clients; the useful signal here is the light client's latency.

## Cache bloat

5,000 sequential requests: 60% drawn from a Zipf(1.1) catalog of 2,000 popular prompts, 40% one-off
prompts that never repeat. Same 2 MB cache memory cap for both runs.

| run | hit rate | model calls | entries stored | evictions | hits per MB |
|---|---|---|---|---|---|
| naive: admit everything + LRU | 29.0% | 3,550 | 607 | 2,943 | 725 |
| smart: second-sight admission + LFU | 29.2% | 3,540 | **277** | **413** | 730 |

Same hit rate, but the smart cache stored less than half the entries and evicted **7x less**: the
one-off prompts no longer churn through the cache. (Memory reads the same because both runs fill the
cap; the smart run's cap also holds the small "seen once" markers.) The hit-rate gain is small at this
memory size because the popular set nearly fits either way.

### Shared-pool pollution

Shared scope. Key A floods unique prompts, sending each **twice** (so they pass second-sight
admission); key B sends popular prompts. B's hit rate:

| insert budget per key | B hit rate |
|---|---|
| none | 40.1% |
| 30 new entries / minute | 34.9% |

**The insert budget did not help in this benchmark; it hurt.** The run compresses ~1,250 tenant
requests into seconds, so a per-minute budget also throttles tenant B's *own* inserts while B is
filling the cache with its popular prompts. Meanwhile LFU eviction plus admission already kept A's
flood (entries that are hit at most once more) from displacing B's frequently used entries. Insert
budgets remain useful against sustained floods over real time, but they need to be sized to real
traffic; this benchmark does not show a benefit and we report it as measured.
