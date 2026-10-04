"""End-to-end smoke test: the official OpenAI SDK against a running gateway, only base_url changed.

Usage: python scripts/smoke_openai.py [--base-url http://localhost:8000/v1] [--model fast]
"""

import argparse
import time

from openai import OpenAI


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--model", default="fast")
    parser.add_argument("--api-key", default="tg_placeholder")  # enforced from Phase 2
    args = parser.parse_args()

    client = OpenAI(base_url=args.base_url, api_key=args.api_key)
    print("models:", [m.id for m in client.models.list()])

    start = time.perf_counter()
    resp = client.chat.completions.create(
        model=args.model,
        messages=[{"role": "user", "content": "Reply with exactly: pong"}],
        temperature=0,
    )
    print(f"non-stream ({time.perf_counter() - start:.1f}s):", repr(resp.choices[0].message.content), resp.usage)

    start = time.perf_counter()
    stream = client.chat.completions.create(
        model=args.model,
        messages=[{"role": "user", "content": "Count from 1 to 10, one number per line."}],
        stream=True,
    )
    chunks, text, usage, first = 0, "", None, None
    for chunk in stream:
        chunks += 1
        if chunk.choices and chunk.choices[0].delta.content:
            first = first or time.perf_counter() - start
            text += chunk.choices[0].delta.content
        usage = chunk.usage or usage
    print(f"stream: {chunks} chunks, first token {first or 0:.1f}s, total {time.perf_counter() - start:.1f}s")
    print("stream text:", repr(text), usage)


if __name__ == "__main__":
    main()
