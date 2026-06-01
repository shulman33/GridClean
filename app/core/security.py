"""API-key authentication and request principals.

Endpoints are usable anonymously (rate-limited by client IP); supplying a
valid `X-API-Key` raises the caller to that key's tier and limit. Raw keys are
hashed (SHA-256) before any comparison — we never store or log them.
"""

import hashlib
import secrets
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session
from app.models import ApiKey

KEY_PREFIX = "gck_"  # GridClean key


@dataclass(frozen=True)
class Principal:
    identity: str  # rate-limit bucket key, e.g. "key:3" or "ip:1.2.3.4"
    tier: str
    limit_per_min: int


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_key() -> tuple[str, str]:
    """Return (raw_key, key_hash). The raw key is shown to the user once."""
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_key(raw)


async def get_principal(
    request: Request,
    x_api_key: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    if x_api_key:
        key = (
            await session.execute(
                select(ApiKey).where(
                    ApiKey.key_hash == hash_key(x_api_key),
                    ApiKey.active.is_(True),
                    ApiKey.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if key is None:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
        return Principal(
            identity=f"key:{key.id}", tier=key.tier, limit_per_min=key.rate_limit_per_min
        )

    client_ip = request.client.host if request.client else "unknown"
    return Principal(
        identity=f"ip:{client_ip}",
        tier="anonymous",
        limit_per_min=get_settings().anonymous_rate_limit_per_min,
    )
