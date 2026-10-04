"""Cache bloat benchmark: naive (admit everything + LRU) vs smart (second-sight admission + LFU).

Both runs use the same cache Redis memory cap and the same 5,000-request workload (Zipf-popular
prompts mixed with one-off prompts). A pollution test then checks whether per-key insert budgets
protect a well-behaved tenant in a shared pool from a tenant flooding it.

Needs a real Redis for the cache (memory and evictions are what is measured), with CONFIG allowed:
  docker compose -f docker-compose.yml -f compose.dev.yml up -d redis redis-cache
  python -m bench.cache_bench --redis-url redis://localhost:6379/0 --cache-url redis://localhost:6381/0
"""

import argparse
import asyncio
import json
import random
from pathlib import Path

import redis.asyncio as aioredis

from bench.harness import SimulatedModel, chat, create_key, gateway, table
from bench.workload import answer_for, mixed_prompts

RESULTS = Path(__file__).parent / "results"


async def reset_cache(url: str, policy: str, maxmemory: str) -> None:
    r = aioredis.from_url(url)
    await r.flushall()
    await r.config_set("maxmemory", maxmemory)
    await r.config_set("maxmemory-policy", policy)
    await r.config_resetstat()
    await r.aclose()


async def cache_info(url: str) -> dict[str, int]:
    r = aioredis.from_url(url, decode_responses=True)
    memory, stats = await r.info("memory"), await r.info("stats")
    entries = 0
    async for _ in r.scan_iter(match="cache:*", count=1000):
        entries += 1
    await r.aclose()
    return {"used_memory": int(memory["used_memory"]), "evicted": int(stats["evicted_keys"]), "entries": entries}


async def run_mix(args: argparse.Namespace, *, admission: str, policy: str) -> dict[str, float]:
    await reset_cache(args.cache_url, policy, args.maxmemory)
    model = SimulatedModel(content=answer_for)
    prompts = mixed_prompts(args.requests, exponent=args.zipf, one_off_ratio=args.one_off)
    hits = 0
    async with gateway(model, redis_url=args.redis_url, redis_cache_url=args.cache_url, cache_admission=admission) as c:
        auth = await create_key(c, "bench")
        for prompt in prompts:  # sequential: measures the cache, not concurrency
            resp = await chat(c, auth, prompt, temperature=0)
            hits += resp.headers.get("x-tollgate-cache") == "hit"
    info = await cache_info(args.cache_url)
    mb = info["used_memory"] / 1_048_576
    return {
        "hit_rate": hits / len(prompts),
        "hits": hits,
        "model_calls": model.calls,
        "entries": info["entries"],
        "memory_mb": round(mb, 2),
        "evictions": info["evicted"],
        "hits_per_mb": round(hits / mb, 1) if mb else 0.0,
    }


async def run_pollution(args: argparse.Namespace, *, budget: int) -> float:
    """Shared pool. Key A floods unique prompts, sending each twice (retries pass second-sight
    admission); key B sends popular prompts. Returns B's hit rate: B requests that never reached
    the model (shared scope hides x-tollgate-cache from callers)."""
    await reset_cache(args.cache_url, "allkeys-lfu", args.maxmemory)
    model = SimulatedModel(content=answer_for)
    rng = random.Random(11)
    b_prompts = mixed_prompts(args.requests // 4, one_off_ratio=0.0, catalog=300, seed=3)
    overrides = {"cache_insert_budget_per_min": budget}
    async with gateway(model, redis_url=args.redis_url, redis_cache_url=args.cache_url, **overrides) as c:
        a, b = await create_key(c, "flooder"), await create_key(c, "tenant")
        for i, prompt in enumerate(b_prompts):
            for j in range(3):  # 6 flood requests (3 unique prompts x 2) per tenant request
                flood = f"flood {i}-{j} {rng.random():.12f}"
                await chat(c, a, flood, model="faq", temperature=0)
                await chat(c, a, flood, model="faq", temperature=0)
            await chat(c, b, prompt, model="faq", temperature=0)
    b_set = set(b_prompts)
    b_model_calls = sum(1 for p, _ in model.served if p in b_set)
    return (len(b_prompts) - b_model_calls) / len(b_prompts)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--cache-url", required=True)
    parser.add_argument("--requests", type=int, default=5_000)
    parser.add_argument("--maxmemory", default="2mb")
    parser.add_argument("--zipf", type=float, default=1.1)
    parser.add_argument("--one-off", type=float, default=0.4)
    args = parser.parse_args()

    naive = await run_mix(args, admission="always", policy="allkeys-lru")
    smart = await run_mix(args, admission="second_sight", policy="allkeys-lfu")
    rows = [
        [name, f"{r['hit_rate']:.1%}", r["model_calls"], r["entries"], r["memory_mb"], r["evictions"], r["hits_per_mb"]]
        for name, r in (("naive (admit all + LRU)", naive), ("smart (second sight + LFU)", smart))
    ]
    print(
        f"\nCache bloat: {args.requests} requests, Zipf {args.zipf}, "
        f"{args.one_off:.0%} one-off, maxmemory {args.maxmemory}\n"
    )
    print(table(["run", "hit rate", "model calls", "entries", "memory MB", "evictions", "hits/MB"], rows))

    without = await run_pollution(args, budget=1_000_000)
    with_budget = await run_pollution(args, budget=30)
    print("\nShared-pool pollution: tenant B's hit rate while key A floods\n")
    print(
        table(["insert budget", "B hit rate"], [["none", f"{without:.1%}"], ["30 / key / min", f"{with_budget:.1%}"]])
    )

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "cache.json").write_text(
        json.dumps(
            {
                "config": vars(args),
                "naive": naive,
                "smart": smart,
                "pollution": {"no_budget": without, "budget_30": with_budget},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
