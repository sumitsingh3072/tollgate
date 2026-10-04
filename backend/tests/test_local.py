"""Local mode (opt-in): Ollama provider, model readiness in /health, generated admin token file."""

import json
from pathlib import Path

import httpx
import pytest
import respx
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import DEFAULT_ADMIN_TOKEN, Settings, build_aliases
from app.db.session import create_sessionmaker
from app.logging_queue import LogQueue
from app.main import create_app

pytestmark = pytest.mark.respx(assert_all_called=False)

OLLAMA = "http://ollama.test:11434/v1"


@pytest.fixture
def local_settings() -> Settings:
    return Settings(
        _env_file=None, environment="test", upstream_provider="ollama", ollama_base_url=OLLAMA, admin_token="test-admin"
    )


@pytest.fixture
async def local_client(local_settings: Settings, redis: FakeAsyncRedis, engine: AsyncEngine, http: httpx.AsyncClient):
    app = create_app(local_settings, use_lifespan=False)
    app.state.redis, app.state.engine, app.state.http = redis, engine, http
    app.state.redis_cache = redis
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.log_queue = LogQueue(app.state.sessionmaker, 2)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def test_gemini_is_the_default_provider() -> None:
    assert Settings(_env_file=None).upstream_provider == "gemini"


def test_ollama_aliases() -> None:
    settings = Settings(_env_file=None, upstream_provider="ollama")
    aliases = build_aliases(settings)
    assert [u.model for u in aliases["smart"].chain] == ["gemma3:4b", "gemma3:1b"]
    assert all(u.base_url == "http://localhost:11434/v1" and u.api_key == "" for u in aliases["smart"].chain)
    assert aliases["fast"].chain[0].default_params == {}  # no Gemini-only extra_body


@pytest.mark.parametrize(
    ("pulled", "models", "status"),
    [(["gemma3:1b", "gemma3:4b"], True, "ok"), (["gemma3:1b"], False, "degraded"), ([], False, "degraded")],
)
async def test_health_reports_model_readiness(
    local_client, respx_mock: respx.MockRouter, pulled, models, status
) -> None:
    respx_mock.get(f"{OLLAMA}/models").mock(
        return_value=httpx.Response(200, json={"object": "list", "data": [{"id": m} for m in pulled]})
    )
    body = (await local_client.get("/health")).json()
    assert (body["upstream"], body["status"], body["provider"]) == (models, status, "ollama")


async def test_health_when_ollama_unreachable(local_client, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{OLLAMA}/models").mock(side_effect=httpx.ConnectError("down"))
    body = (await local_client.get("/health")).json()
    assert body["upstream"] is False and body["status"] == "degraded"


async def test_chat_goes_to_ollama_without_auth_header(local_client, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{OLLAMA}/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "hi"}}], "usage": {"total_tokens": 3}}
        )
    )
    key = (
        await local_client.post("/admin/keys", json={"name": "k"}, headers={"Authorization": "Bearer test-admin"})
    ).json()["key"]

    resp = await local_client.post(
        "/v1/chat/completions",
        json={"model": "fast", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {key}"},
    )

    assert resp.status_code == 200 and resp.headers["x-tollgate-model"] == "gemma3:1b"
    sent = route.calls.last.request
    assert "authorization" not in sent.headers
    assert json.loads(sent.content)["model"] == "gemma3:1b"


def test_admin_token_read_from_file(tmp_path: Path) -> None:
    token_file = tmp_path / "admin_token"
    token_file.write_text("generated-secret\n")
    assert Settings(_env_file=None, admin_token_file=token_file).admin_token.get_secret_value() == "generated-secret"
    explicit = Settings(_env_file=None, admin_token="explicit", admin_token_file=token_file)
    assert explicit.admin_token.get_secret_value() == "explicit"  # an explicit token wins
    # Empty or placeholder values mean "not set", exactly as in the dashboard.
    for placeholder in ("", "  ", DEFAULT_ADMIN_TOKEN):
        s = Settings(_env_file=None, admin_token=placeholder, admin_token_file=token_file)
        assert s.admin_token.get_secret_value() == "generated-secret"


def test_admin_token_file_must_be_readable(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not readable"):
        Settings(_env_file=None, admin_token_file=tmp_path / "nope")
    empty = tmp_path / "empty"
    empty.write_text("")
    with pytest.raises(ValueError, match="empty"):
        Settings(_env_file=None, admin_token_file=empty)


def test_default_admin_token_refused_in_production() -> None:
    from app.main import _check_admin_token

    with pytest.raises(RuntimeError):
        _check_admin_token(Settings(_env_file=None, environment="production"))
    _check_admin_token(Settings(_env_file=None, environment="development"))  # only a warning
