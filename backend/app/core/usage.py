"""Token usage extraction for JSON and SSE responses, with a chars/4 estimate when upstream omits it."""

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated: bool = False


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def prompt_text(messages: Iterable[Mapping[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(str(p.get("text", "")) for p in content if isinstance(p, Mapping))
    return "\n".join(parts)


def from_usage_dict(usage: Any) -> Usage | None:
    if not isinstance(usage, Mapping):
        return None
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    # total_tokens can exceed prompt+completion (e.g. Gemma thinking tokens); bill the larger number.
    total = max(int(usage.get("total_tokens") or 0), prompt + completion)
    return Usage(prompt, completion, total) if total else None


def estimate(prompt: str, completion: str) -> Usage:
    p, c = estimate_tokens(prompt), estimate_tokens(completion)
    return Usage(p, c, p + c, estimated=True)


def from_completion(body: Mapping[str, Any], prompt: str) -> Usage:
    usage = from_usage_dict(body.get("usage"))
    if usage:
        return usage
    choices = body.get("choices") or []
    completion = "".join(str((c.get("message") or {}).get("content") or "") for c in choices if isinstance(c, Mapping))
    return estimate(prompt, completion)


class SSEUsageTracker:
    """Fed raw SSE bytes as they stream by; remembers the last usage block and counts content chars.

    Lines can be split across network chunks, so partial lines are buffered.
    """

    def __init__(self, prompt: str) -> None:
        self._prompt = prompt
        self._buffer = b""
        self._usage: Usage | None = None
        self._content: list[str] = []
        self._chars = 0

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk
        *lines, self._buffer = self._buffer.split(b"\n")
        for line in lines:
            self._parse(line.strip())

    def _parse(self, line: bytes) -> None:
        if not line.startswith(b"data:"):
            return
        data = line[5:].strip()
        if not data or data == b"[DONE]":
            return
        try:
            event = json.loads(data)
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        self._usage = from_usage_dict(event.get("usage")) or self._usage
        for choice in event.get("choices") or []:
            content = (choice.get("delta") or {}).get("content") if isinstance(choice, dict) else None
            if isinstance(content, str):
                self._content.append(content)
                self._chars += len(content)

    @property
    def content_seen(self) -> bool:
        return bool(self._content)

    @property
    def content_chars(self) -> int:
        return self._chars

    def result(self) -> Usage:
        if self._buffer:
            self._parse(self._buffer.strip())
            self._buffer = b""
        return self._usage or estimate(self._prompt, "".join(self._content))
