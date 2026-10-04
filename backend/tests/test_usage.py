from app.core.usage import SSEUsageTracker, estimate_tokens, from_completion, from_usage_dict, prompt_text


def test_total_includes_hidden_thinking_tokens() -> None:
    # Gemma reports thinking tokens only in total_tokens.
    usage = from_usage_dict({"prompt_tokens": 11, "completion_tokens": 1, "total_tokens": 59})
    assert usage is not None and usage.total_tokens == 59


def test_completion_without_usage_is_estimated() -> None:
    body = {"choices": [{"message": {"content": "x" * 40}}]}
    usage = from_completion(body, prompt="y" * 8)
    assert (usage.prompt_tokens, usage.completion_tokens, usage.estimated) == (2, 10, True)


def test_prompt_text_handles_content_parts() -> None:
    messages = [{"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "image_url"}]}, {"content": "b"}]
    assert prompt_text(messages) == "a\n\nb"


def test_sse_tracker_estimates_when_no_usage() -> None:
    tracker = SSEUsageTracker(prompt="")
    tracker.feed(b'data: {"choices":[{"delta":{"content":"abcd"}}]}\n\ndata: {"choi')
    tracker.feed(b'ces":[{"delta":{"content":"efgh"}}]}\n\ndata: [DONE]\n\n')
    usage = tracker.result()
    assert usage.estimated and usage.completion_tokens == estimate_tokens("abcdefgh")


def test_sse_tracker_ignores_garbage() -> None:
    tracker = SSEUsageTracker(prompt="")
    tracker.feed(b": keep-alive\n\ndata: not-json\n\ndata: []\n\n")
    assert tracker.result().total_tokens == 0
