"""Settings (from env / .env) and model alias chains."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.cache import CachePolicy

DEFAULT_ADMIN_TOKEN = "change-me"


class Settings(BaseSettings):
    # Root .env is shared with docker compose; backend/.env (if present) overrides it.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"

    database_url: str = "postgresql+asyncpg://tollgate:tollgate@localhost:5432/tollgate"
    # State (keys, limits, quotas) must never be evicted; the response cache lives in its own
    # Redis with allkeys-lfu and a memory cap. Unset REDIS_CACHE_URL = share the state instance.
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_url: str | None = None

    # Where models run: "gemini" (default, Google's hosted API: light on the machine) or "ollama"
    # (fully local; start compose with --profile ollama).
    upstream_provider: Literal["gemini", "ollama"] = "gemini"
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_fast_model: str = "gemma3:1b"
    ollama_smart_model: str = "gemma3:4b"

    gemini_api_key: SecretStr = SecretStr("")
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_fast_model: str = "gemma-4-26b-a4b-it"
    gemini_smart_model: str = "gemma-4-31b-it"
    # Gemma thinks by default and inlines <thought>...</thought> into content; "minimal" turns that off.
    # Empty string leaves the model default. Clients can override per request via extra_body.
    gemini_thinking_level: Literal["minimal", "high", ""] = "minimal"
    mock_upstream_url: str = "http://localhost:9000/v1"

    admin_token: SecretStr = SecretStr(DEFAULT_ADMIN_TOKEN)
    # Zero-config deployments generate the token into a shared file (docker compose secrets-init).
    # An explicit ADMIN_TOKEN always wins.
    admin_token_file: Path | None = None
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    key_cache_ttl: int = 60
    log_flush_interval: float = 2.0
    upstream_timeout: float = 120.0  # local models on CPU are slow, especially on first load
    upstream_connect_timeout: float = 5.0

    # Caps for self-serve (signed-in) users, who share the gateway's upstream capacity.
    user_max_keys: int = 5
    user_max_rpm: int = 120
    user_max_daily_tokens: int = 500_000

    cache_ttl: int = 86_400  # per-route default; stale answers expire even when popular
    cache_max_entry_bytes: int = 16_384
    cache_seen_ttl: int = 3_600  # second-sight admission window
    # Identical in-flight requests share one upstream call (per process: run one worker).
    coalescing_enabled: bool = True
    breaker_failure_threshold: int = 3
    breaker_open_seconds: float = 30.0

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, v: str) -> str:
        return normalize_database_url(v)

    @model_validator(mode="after")
    def _admin_token_from_file(self) -> "Settings":
        if self.admin_token.get_secret_value() == DEFAULT_ADMIN_TOKEN and self.admin_token_file:
            try:
                token = self.admin_token_file.read_text().strip()
            except OSError:
                token = ""
            if token:
                self.admin_token = SecretStr(token)
        return self

    @field_validator("gemini_base_url", "mock_upstream_url", "ollama_base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, v: str) -> str:
        return v.upper()


def normalize_database_url(url: str) -> str:
    """Make a Neon/libpq URL usable by SQLAlchemy + asyncpg.

    asyncpg rejects libpq-only params (sslmode, channel_binding); it takes ssl=.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    query: list[tuple[str, str]] = []
    for k, v in parse_qsl(parts.query):
        if k == "sslmode":
            query.append(("ssl", v))
        elif k != "channel_binding":
            query.append((k, v))
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@lru_cache
def get_settings() -> Settings:
    return Settings()


@dataclass(frozen=True)
class Upstream:
    """One OpenAI-compatible endpoint + model. api_key is kept out of repr/logs.

    default_params are deep-merged under the client's request body (client values win).
    """

    model: str
    base_url: str
    api_key: str = field(default="", repr=False)
    default_params: Mapping[str, Any] = field(default_factory=dict, hash=False, compare=False)


@dataclass(frozen=True)
class Alias:
    chain: tuple[Upstream, ...]
    terse: bool = False
    cache: CachePolicy = field(default_factory=CachePolicy)


def upstream_models(settings: Settings) -> tuple[Upstream, Upstream]:
    """(fast, smart) for the configured provider."""
    if settings.upstream_provider == "ollama":
        # Ollama's OpenAI-compatible API needs no key.
        return (
            Upstream(settings.ollama_fast_model, settings.ollama_base_url),
            Upstream(settings.ollama_smart_model, settings.ollama_base_url),
        )
    key = settings.gemini_api_key.get_secret_value()
    params = _gemini_params(settings)
    return (
        Upstream(settings.gemini_fast_model, settings.gemini_base_url, key, params),
        Upstream(settings.gemini_smart_model, settings.gemini_base_url, key, params),
    )


def build_aliases(settings: Settings) -> dict[str, Alias]:
    fast, smart = upstream_models(settings)
    smart_chain = (smart, fast)
    cache = CachePolicy(ttl_seconds=settings.cache_ttl)
    # Always-500 upstream first, so failover can be demoed on demand.
    mock = Upstream("mock-500", settings.mock_upstream_url)
    return {
        "fast": Alias(chain=(fast,), cache=cache),
        "smart": Alias(chain=smart_chain, cache=cache),
        "smart-terse": Alias(chain=smart_chain, terse=True, cache=cache),
        "demo-failover": Alias(chain=(mock, fast), cache=cache),
    }


def _gemini_params(settings: Settings) -> dict[str, Any]:
    if not settings.gemini_thinking_level:
        return {}
    # Gemini's OpenAI-compat layer reads vendor options from a literal "extra_body" JSON field.
    return {"extra_body": {"google": {"thinking_config": {"thinking_level": settings.gemini_thinking_level}}}}
