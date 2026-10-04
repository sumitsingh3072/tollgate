"""Coalescing benchmark: 50 identical concurrent requests, coalescing on vs off.

python -m bench.coalesce_bench
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from bench.harness import SimulatedModel, chat, create_key, gateway, table

RESULTS = Path(__file__).parent / "results"


async def run(clients: int, latency_s: float, *, enabled: bool) -> dict[str, float]:
    model = SimulatedModel(slots=4, prefill_s=latency_s)
    # A queue deep enough for every client, so the comparison is about coalescing, not backpressure.
    async with gateway(model, coalescing_enabled=enabled, upstream_max_parallel=4, fair_max_queue_per_key=clients) as c:
        auth = await create_key(c, "bench")
        start = time.perf_counter()
        responses = await asyncio.gather(
            *(chat(c, auth, "the same question everyone asks", temperature=0) for _ in range(clients))
        )
        elapsed = time.perf_counter() - start
    return {
        "upstream_calls": model.calls,
        "clients_served": sum(r.status_code == 200 for r in responses),
        "total_s": round(elapsed, 2),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clients", type=int, default=50)
    parser.add_argument("--latency", type=float, default=0.5, help="simulated model time per call (s)")
    args = parser.parse_args()

    off = await run(args.clients, args.latency, enabled=False)
    on = await run(args.clients, args.latency, enabled=True)
    print(
        f"\nCoalescing: {args.clients} identical concurrent requests, {args.latency}s per model call, 4 model slots\n"
    )
    print(
        table(
            ["coalescing", "upstream calls", "clients served", "total time (s)"],
            [
                ["off", off["upstream_calls"], off["clients_served"], off["total_s"]],
                ["on", on["upstream_calls"], on["clients_served"], on["total_s"]],
            ],
        )
    )
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "coalesce.json").write_text(json.dumps({"config": vars(args), "off": off, "on": on}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
