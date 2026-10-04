"""Terse-mode system prompt injection for *-terse aliases."""

from typing import Any

TERSE_PROMPT = (
    "Be terse. Answer with the minimum words needed to be correct and complete. "
    "No preamble, no restating the question, no pleasantries, no closing summary. "
    "Prefer fragments and lists over prose. Keep code, numbers, names and technical terms exact."
)


def apply(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepend the terse instruction, merging into an existing leading system message when possible."""
    if messages and messages[0].get("role") in ("system", "developer") and isinstance(messages[0].get("content"), str):
        first = messages[0]
        return [{**first, "content": f"{TERSE_PROMPT}\n\n{first['content']}"}, *messages[1:]]
    return [{"role": "system", "content": TERSE_PROMPT}, *messages]
