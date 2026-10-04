"""Tags, TTFT, new log filters and the Prometheus endpoint."""

import httpx
import pytest
import respx
from fastapi import FastAPI

from app.config import Settings
from app.core.tags import parse_tags
from tests.conftest import ADMIN_HEADERS

pytestmark = pytest.mark.respx(assert_all_called=False)

MESSAGES = [{"role": "user", "content": "hi"}]
COMPLETION = {
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
}


@pytest.fixture
def gemini(settings: Settings, respx_mock: respx.MockRouter) -> respx.Route:
    return respx_mock.post(f"{settings.gemini_base_url}/chat/completions").mock(
        return_value=httpx.Response(200, json=COMPLETION)
    )


def test_parse_tags() -> None:
    assert parse_tags("feature=search, team=growth") == {"feature": "search", "team": "growth"}
    assert parse_tags("bad, a=1, =x, y=, sp ace=v, ok=yes") == {"a": "1", "ok": "yes"}
    assert parse_tags("") is None and parse_tags(None) is None
    assert len(parse_tags(",".join(f"k{i}=v" for i in range(20)))) == 10


async def test_tags_logged_and_filterable(client, auth, app: FastAPI, gemini) -> None:
    for tags in ("feature=search,team=growth", "feature=chat"):
        await client.post(
            "/v1/chat/completions",
            json={"model": "fast", "messages": MESSAGES},
            headers={**auth, "x-tollgate-tags": tags},
        )
    await app.state.log_queue.flush()

    search = (await client.get("/admin/logs?tag=feature=search", headers=ADMIN_HEADERS)).json()["items"]
    ineligible = (await client.get("/admin/logs?cache_status=ineligible", headers=ADMIN_HEADERS)).json()["items"]

    assert [i["tags"] for i in search] == [{"feature": "search", "team": "growth"}]
    assert len(ineligible) == 2  # no temperature given: not deterministic, so not cacheable
    bad = await client.get("/admin/logs?cache_status=bogus", headers=ADMIN_HEADERS)
    assert bad.status_code == 422


async def test_metrics_requires_admin_and_reports(client, auth, gemini) -> None:
    await client.post(
        "/v1/chat/completions", json={"model": "fast", "messages": MESSAGES, "temperature": 0}, headers=auth
    )

    assert (await client.get("/metrics")).status_code == 401
    resp = await client.get("/metrics", headers=ADMIN_HEADERS)

    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert 'gen_ai_client_operation_duration_seconds_count{gen_ai_request_model="fast",status_class="2xx"}' in body
    assert 'gen_ai_client_token_usage_bucket{gen_ai_request_model="fast",le="4.0",token_type="input"}' in body
    assert 'tollgate_cache_requests_total{status="admission_rejected"}' in body
    assert "tollgate_cache_admission_rejected_total" in body
