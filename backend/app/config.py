"""Settings (from env / .env) and model alias chains."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_ADMIN_TOKEN = "change-me"


class Settings(BaseSettings):
    # Root .env is shared with docker compose; backend/.env (if present) overrides it.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"

    database_url: str = "postgresql+asyncpg://tollgate:tollgate@localhost:5432/tollgate"
    redis_url: str = "redis://localhost:6379/0"

    gemini_api_key: SecretStr = SecretStr("")
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_fast_model: str = "gemma-4-26b-a4b-it"
    gemini_smart_model: str = "gemma-4-31b-it"
    # Gemma thinks by default and inlines <thought>...</thought> into content; "minimal" turns that off.
    # Empty string leaves the model default. Clients can override per request via extra_body.
    gemini_thinking_level: Literal["minimal", "high", ""] = "minimal"
    mock_upstream_url: str = "http://localhost:9000/v1"

    admin_token: SecretStr = SecretStr(DEFAULT_ADMIN_TOKEN)
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    key_cache_ttl: int = 60
    log_flush_interval: float = 2.0
    upstream_timeout: float = 60.0
    upstream_connect_timeout: float = 5.0

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, v: str) -> str:
        return normalize_database_url(v)

    @field_validator("gemini_base_url", "mock_upstream_url")
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


def build_aliases(settings: Settings) -> dict[str, Alias]:
    key = settings.gemini_api_key.get_secret_value()
    params = _gemini_params(settings)
    fast = Upstream(settings.gemini_fast_model, settings.gemini_base_url, key, params)
    smart = Upstream(settings.gemini_smart_model, settings.gemini_base_url, key, params)
    smart_chain = (smart, fast)
    return {
        "fast": Alias(chain=(fast,)),
        "smart": Alias(chain=smart_chain),
        "smart-terse": Alias(chain=smart_chain, terse=True),
    }


def _gemini_params(settings: Settings) -> dict[str, Any]:
    if not settings.gemini_thinking_level:
        return {}
    # Gemini's OpenAI-compat layer reads vendor options from a literal "extra_body" JSON field.
    return {"extra_body": {"google": {"thinking_config": {"thinking_level": settings.gemini_thinking_level}}}}
