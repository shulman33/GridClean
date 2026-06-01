"""Redis response caching with ETag / conditional-request support.

Read-heavy endpoints (/now, /compare) cache their JSON in Redis for a short
TTL and emit an `ETag`. A client that sends a matching `If-None-Match` gets a
304 with no body. Returns either a JSON-able dict (let FastAPI serialize it via
the endpoint's response_model) or a bare 304 Response.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.responses import Response as StarletteResponse

from app.core.redis import get_redis


def _etag(payload: str) -> str:
    return '"' + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32] + '"'


async def cached_json(
    *,
    request: Request,
    response: Response,
    cache_key: str,
    ttl: int,
    build: Callable[[], Awaitable[dict]],
) -> dict | StarletteResponse:
    redis = get_redis()
    payload = await redis.get(cache_key)
    cache_status = "HIT"
    if payload is None:
        data = await build()
        payload = json.dumps(data, default=str, sort_keys=True)
        await redis.set(cache_key, payload, ex=ttl)
        cache_status = "MISS"

    etag = _etag(payload)
    headers = {
        "ETag": etag,
        "Cache-Control": f"public, max-age={ttl}",
        "X-Cache": cache_status,
    }

    if request.headers.get("If-None-Match") == etag:
        return StarletteResponse(status_code=304, headers=headers)

    for key, value in headers.items():
        response.headers[key] = value
    return json.loads(payload)
