"""Request logging + timing middleware.

Assigns each request an ID, times it, attaches `X-Request-ID` and
`X-Response-Time-ms` headers, and emits one structured log line per request
(method, path, status, duration). Per-request durations feed p50/p95/p99 via
log aggregation in production.
"""

import logging
import time
import uuid

from starlette.requests import Request

from app.core.logging import log_event

logger = logging.getLogger("gridclean.request")


async def logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-ms"] = str(duration_ms)

    log_event(
        logger,
        "request",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
        client=request.client.host if request.client else None,
    )
    return response
