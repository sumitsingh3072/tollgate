"""Prompt workloads: a Zipf-popular catalog mixed with a stream of unique one-off prompts."""

import random
import zlib
from collections.abc import Iterator


def zipf_sampler(n_items: int, exponent: float, rng: random.Random) -> Iterator[int]:
    weights = [1 / (rank**exponent) for rank in range(1, n_items + 1)]
    while True:
        yield rng.choices(range(n_items), weights=weights, k=256)  # batched for speed


def mixed_prompts(
    total: int, *, catalog: int = 2_000, exponent: float = 1.1, one_off_ratio: float = 0.4, seed: int = 7
) -> list[str]:
    """`total` prompts: popular ones drawn from a Zipf(`exponent`) catalog, the rest never repeat."""
    rng = random.Random(seed)
    popular = zipf_sampler(catalog, exponent, rng)
    batch: list[int] = []
    prompts = []
    for i in range(total):
        if rng.random() < one_off_ratio:
            prompts.append(f"one-off question #{i} {rng.random():.12f}")
        else:
            if not batch:
                batch = list(next(popular))
            prompts.append(f"popular question #{batch.pop()}: how do I configure feature {i % 7}?")
    return prompts


def answer_for(prompt: str) -> str:
    """A deterministic answer of realistic size (300-1500 chars) for a prompt."""
    size = 300 + (zlib.crc32(prompt.encode()) % 1200)  # stable across runs, unlike hash()
    return ("Here is how to do it. " * 80)[:size]
