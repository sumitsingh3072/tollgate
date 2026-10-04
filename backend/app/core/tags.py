"""Cost-attribution tags from the x-tollgate-tags header, e.g. "feature=search,team=growth"."""

import re

TAGS_HEADER = "x-tollgate-tags"
_MAX_TAGS = 10
_TOKEN = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def parse_tags(raw: str | None) -> dict[str, str] | None:
    """Valid key=value pairs only; malformed pairs are dropped rather than failing the request."""
    if not raw:
        return None
    tags: dict[str, str] = {}
    for pair in raw.split(","):
        key, sep, value = pair.partition("=")
        key, value = key.strip(), value.strip()
        if sep and _TOKEN.fullmatch(key) and _TOKEN.fullmatch(value) and len(tags) < _MAX_TAGS:
            tags[key] = value
    return tags or None
