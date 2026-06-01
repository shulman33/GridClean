"""Async SQLAlchemy engine, session factory, and declarative base."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings

settings = get_settings()

# Under tests, pytest-asyncio runs each test in its own event loop; a pooled
# asyncpg connection bound to a previous loop raises "another operation is in
# progress". NullPool opens a fresh connection per use, sidestepping this.
#
# In prod, the managed Postgres (Neon) drops idle connections after a few
# minutes. Without pre-ping the pool hands out a dead connection and the next
# request fails with asyncpg "connection is closed". pool_pre_ping issues a
# cheap liveness check (and transparently reconnects) before each checkout;
# pool_recycle proactively retires connections before the server's idle window.
_engine_kwargs: dict = {
    "echo": settings.debug,
    "future": True,
    "pool_pre_ping": True,
    "pool_recycle": 300,
}
if settings.environment == "test":
    _engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(settings.database_url, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a database session."""
    async with SessionLocal() as session:
        yield session
