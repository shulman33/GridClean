"""Redis fixed-window rate limiting, applied as a FastAPI dependency.

Sets standard `X-RateLimit-*` headers on every response and returns 429 with
`Retry-After` when a caller exceeds their per-minute quota. Throttle events are
logged structurally (who, where) so limit-hitting is observable.
"""

import logging
import time

from fastapi import Depends, HTTPException, Request, Response

from app.core.logging import log_event
from app.core.redis import get_redis
from app.core.security import Principal, get_principal

logger = logging.getLogger("gridclean.ratelimit")


async def enforce_rate_limit(
    request: Request,
    response: Response,
    principal: Principal = Depends(get_principal),
) -> Principal:
    redis = get_redis()
    window = int(time.time() // 60)
    reset_at = (window + 1) * 60
    key = f"rl:{principal.identity}:{window}"

    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)

    limit = principal.limit_per_min
    remaining = max(0, limit - count)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset_at)

    if count > limit:
        retry_after = reset_at - int(time.time())
        log_event(
            logger,
            "rate_limit_exceeded",
            identity=principal.identity,
            tier=principal.tier,
            path=request.url.path,
            limit=limit,
        )
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded.",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_at),
            },
        )
    return principal
