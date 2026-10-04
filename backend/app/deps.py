"""Auth (Bearer tg key -> Redis-cached lookup) and admin-token dependencies."""

import hmac
import logging
import re
from dataclasses import dataclass

from fastapi import Request

from app.config import Settings
from app.core import keys
from app.core.keys import KeyRecord
from app.db import queries
from app.errors import GatewayError

log = logging.getLogger("tollgate.auth")

_INVALID_KEY = "Invalid API key. Create one in the Tollgate dashboard."
USER_HEADER = "x-tollgate-user"
_VALID_USER_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


@dataclass(frozen=True)
class AdminScope:
    """Who an admin request acts for. owner_id=None is the operator (ADMIN_TOKEN only) view of everything."""

    owner_id: str | None

    @property
    def is_operator(self) -> bool:
        return self.owner_id is None


def _bearer(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise GatewayError(401, "authentication_error", "Missing API key. Send 'Authorization: Bearer <key>'.")
    return token.strip()


async def require_admin(request: Request) -> None:
    settings: Settings = request.app.state.settings
    expected = settings.admin_token.get_secret_value().encode()
    if not hmac.compare_digest(_bearer(request).encode(), expected):
        raise GatewayError(401, "authentication_error", "Invalid admin token.")


async def admin_scope(request: Request) -> AdminScope:
    """The dashboard forwards the signed-in Clerk user as X-Tollgate-User. It is trusted only because
    the router already required ADMIN_TOKEN, which never leaves the dashboard's server."""
    raw = request.headers.get(USER_HEADER)
    if raw is None:
        return AdminScope(owner_id=None)
    if not _VALID_USER_ID.fullmatch(raw):
        raise GatewayError(400, "invalid_request_error", "Malformed X-Tollgate-User header.")
    return AdminScope(owner_id=raw)


async def require_api_key(request: Request) -> KeyRecord:
    """Redis first (KEY_CACHE_TTL), DB on miss; unknown and revoked keys are cached as invalid too."""
    raw = _bearer(request)
    if not keys.looks_like_key(raw):
        raise GatewayError(401, "authentication_error", _INVALID_KEY)

    redis = request.app.state.redis
    key_hash = keys.hash_key(raw)
    cached = await keys.cache_get(redis, key_hash)
    if cached is False:
        raise GatewayError(401, "authentication_error", _INVALID_KEY)
    if cached is not None:
        return cached

    async with request.app.state.sessionmaker() as session:
        row = await queries.get_active_key_by_hash(session, key_hash)
    record = KeyRecord(id=row.id, name=row.name, rpm=row.rpm, daily_token_quota=row.daily_token_quota) if row else None
    await keys.cache_set(redis, key_hash, record, request.app.state.settings.key_cache_ttl)
    if record is None:
        log.info("rejected unknown or revoked key", extra={"prefix": raw[: keys.DISPLAY_PREFIX_LENGTH]})
        raise GatewayError(401, "authentication_error", _INVALID_KEY)
    return record
