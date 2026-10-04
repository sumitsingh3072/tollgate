"""Fairness benchmark: a heavy client saturating the model vs a light interactive client.

Heavy: keeps 20 long requests in flight. Light: one short request every 2 s. The model has one slot.
Compares the light client's latency with no gateway queue (the model server's FIFO decides), a
gateway FIFO queue, and the VTC fair queue. Also reports Jain's index over tokens served per key.

  python -m bench.fair_bench
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from bench.harness import SimulatedModel, chat, create_key, gateway, jain, percentile, table

RESULTS = Path(__file__).parent / "results"


async def run(args: argparse.Namespace, mode: str) -> dict[str, float]:
    model = SimulatedModel(
        slots=1,
        prefill_s=0.01,
        per_token_s=args.per_token,
        output_tokens=lambda p: args.heavy_tokens if p.startswith("heavy") else args.light_tokens,
    )
    tokens = {"heavy": 0, "light": 0}
    light_latency: list[float] = []
    stop = asyncio.Event()

    async with gateway(
        model, fair_queue_mode=mode, upstream_max_parallel=1, fair_max_queue_per_key=50, fair_max_wait_s=600
    ) as c:
        heavy, light = await create_key(c, "heavy"), await create_key(c, "light")

        async def heavy_worker(n: int) -> None:
            i = 0
            while not stop.is_set():
                resp = await chat(c, heavy, f"heavy {n}-{i}")
                tokens["heavy"] += resp.json().get("usage", {}).get("total_tokens", 0) if resp.status_code == 200 else 0
                i += 1

        async def light_client() -> None:
            i = 0
            while not stop.is_set():
                start = time.perf_counter()
                resp = await chat(c, light, f"light {i}")
                light_latency.append(time.perf_counter() - start)
                tokens["light"] += resp.json().get("usage", {}).get("total_tokens", 0) if resp.status_code == 200 else 0
                i += 1
                await asyncio.sleep(args.light_every)

        workers = [asyncio.create_task(heavy_worker(n)) for n in range(args.heavy_concurrency)]
        await asyncio.sleep(0.2)  # let the heavy client build its backlog first
        light_task = asyncio.create_task(light_client())
        await asyncio.sleep(args.duration)
        stop.set()
        await asyncio.gather(light_task, *workers)

    return {
        "light_p50_s": round(percentile(light_latency, 0.5), 3),
        "light_p95_s": round(percentile(light_latency, 0.95), 3),
        "light_requests": len(light_latency),
        "heavy_tokens": tokens["heavy"],
        "light_tokens": tokens["light"],
        "jain_tokens": round(jain([tokens["heavy"], tokens["light"]]), 3),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=20)
    parser.add_argument("--heavy-concurrency", type=int, default=20)
    parser.add_argument("--heavy-tokens", type=int, default=400)
    parser.add_argument("--light-tokens", type=int, default=20)
    parser.add_argument("--per-token", type=float, default=0.001, help="simulated seconds per output token")
    parser.add_argument("--light-every", type=float, default=2.0)
    args = parser.parse_args()

    results = {mode: await run(args, mode) for mode in ("off", "fifo", "fair")}
    labels = {"off": "no gateway queue (model FIFO)", "fifo": "gateway FIFO", "fair": "gateway fair (VTC)"}
    print(
        f"\nFairness: heavy = {args.heavy_concurrency} concurrent x {args.heavy_tokens} tokens, "
        f"light = 1 x {args.light_tokens} tokens every {args.light_every}s, 1 model slot, {args.duration}s\n"
    )
    print(
        table(
            [
                "queue",
                "light p50 (s)",
                "light p95 (s)",
                "light requests",
                "heavy tokens",
                "light tokens",
                "Jain (tokens)",
            ],
            [
                [
                    labels[m],
                    r["light_p50_s"],
                    r["light_p95_s"],
                    r["light_requests"],
                    r["heavy_tokens"],
                    r["light_tokens"],
                    r["jain_tokens"],
                ]
                for m, r in results.items()
            ],
        )
    )
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "fair.json").write_text(json.dumps({"config": vars(args), **results}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
