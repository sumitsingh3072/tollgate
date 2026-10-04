from app.config import Settings, build_aliases, normalize_database_url


def test_normalize_neon_url() -> None:
    url = "postgresql://u:p@ep-x.neon.tech/neondb?sslmode=require&channel_binding=require"
    assert normalize_database_url(url) == "postgresql+asyncpg://u:p@ep-x.neon.tech/neondb?ssl=require"


def test_aliases_use_gemini_models(settings: Settings) -> None:
    aliases = build_aliases(settings)
    assert set(aliases) == {"fast", "smart", "smart-terse", "demo-failover"}
    assert [u.model for u in aliases["smart"].chain] == [settings.gemini_smart_model, settings.gemini_fast_model]
    assert aliases["smart-terse"].terse and not aliases["smart"].terse
    assert all(u.base_url == settings.gemini_base_url and u.api_key == "test-key" for u in aliases["smart"].chain)


def test_api_key_never_in_repr(settings: Settings) -> None:
    assert "test-key" not in repr(build_aliases(settings))
    assert "test-key" not in repr(settings)


def test_cors_origins_from_comma_string() -> None:
    s = Settings(_env_file=None, cors_origins="http://a.test, http://b.test")
    assert s.cors_origins == ["http://a.test", "http://b.test"]


def test_base_url_trailing_slash_stripped() -> None:
    s = Settings(_env_file=None, gemini_base_url="https://x.test/v1beta/openai/")
    assert s.gemini_base_url == "https://x.test/v1beta/openai"


def test_thinking_level_default_and_disable(settings: Settings) -> None:
    params = build_aliases(settings)["fast"].chain[0].default_params
    assert params == {"extra_body": {"google": {"thinking_config": {"thinking_level": "minimal"}}}}

    off = Settings(_env_file=None, gemini_thinking_level="")
    assert build_aliases(off)["fast"].chain[0].default_params == {}
