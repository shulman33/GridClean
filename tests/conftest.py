"""Shared pytest fixtures."""

import os

# Must be set before app modules import settings.
os.environ.setdefault("ENVIRONMENT", "test")  # NullPool engine in tests
# High anonymous limit so the shared per-IP bucket can't flake across tests;
# the 429 test uses an explicit limit=1 API key instead.
os.environ.setdefault("ANONYMOUS_RATE_LIMIT_PER_MIN", "100000")
# Isolate tests on a dedicated Redis DB index so cached responses / rate-limit
# counters never collide with the dev cache (DB 0).
_redis_base = os.environ.get("REDIS_URL", "redis://localhost:6379/0").rsplit("/", 1)[0]
os.environ["REDIS_URL"] = f"{_redis_base}/15"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
async def _redis_isolation():
    """Fresh, empty Redis per test.

    pytest-asyncio runs each test in its own event loop, so a cached async
    Redis client bound to a previous (closed) loop raises 'Event loop is
    closed'. We reset the client and flush the test DB before each test, which
    also guarantees deterministic caching / rate-limit state.
    """
    import app.core.redis as redis_module

    async def _reset():
        if redis_module._redis is not None:
            await redis_module._redis.aclose()
            redis_module._redis = None

    await _reset()
    await redis_module.get_redis().flushdb()
    yield
    await _reset()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
