from app.config import Upstream
from app.core.proxy import build_payload, deep_merge


def test_deep_merge_override_wins_and_nests() -> None:
    base = {"a": 1, "n": {"x": 1, "y": 1}}
    assert deep_merge(base, {"n": {"y": 2}, "b": 3}) == {"a": 1, "n": {"x": 1, "y": 2}, "b": 3}
    assert base == {"a": 1, "n": {"x": 1, "y": 1}}  # inputs untouched


def test_build_payload_keeps_client_stream_options() -> None:
    upstream = Upstream("m", "http://u")
    payload = build_payload({"model": "fast", "stream": True, "stream_options": {"x": 1}}, upstream)
    assert payload["model"] == "m"
    assert payload["stream_options"] == {"x": 1, "include_usage": True}
