"""Shared pytest fixtures."""

import os

# Must be set before app modules import settings (NullPool in test env).
os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
