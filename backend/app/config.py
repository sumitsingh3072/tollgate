"""Settings (from env / .env) and model alias chains."""

from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/tollgate"
    redis_url: str = "redis://localhost:6379/0"
    ollama_base_url: str = "http://localhost:11434/v1"
    mock_upstream_url: str = "http://localhost:9000/v1"
    admin_token: str = "change-me"
    key_cache_ttl: int = 60
    log_flush_interval: float = 2.0
    upstream_timeout: float = 60.0

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, v: str) -> str:
        return normalize_database_url(v)


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
    model: str
    base_url: str


@dataclass(frozen=True)
class Alias:
    chain: list[Upstream] = field(default_factory=list)
    terse: bool = False


def build_aliases(settings: Settings) -> dict[str, Alias]:
    ollama = settings.ollama_base_url
    smart = [Upstream("llama3.2:3b", ollama), Upstream("qwen2.5:1.5b", ollama)]
    return {
        "fast": Alias(chain=[Upstream("qwen2.5:1.5b", ollama)]),
        "smart": Alias(chain=smart),
        "smart-terse": Alias(chain=smart, terse=True),
    }


MODEL_ALIASES: dict[str, Alias] = build_aliases(get_settings())
