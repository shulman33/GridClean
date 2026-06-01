"""Read-only database access for AI-generated SQL.

Defense in depth (the prompt is never the protection — the DB is):
  1. A dedicated `gridclean_ro` login role with SELECT only on the curated
     `ai_*` views (created in the Phase-4 migration). It cannot see base tables.
  2. Per-connection `default_transaction_read_only = on` — writes error at the
     DB level even if everything else is bypassed.
  3. `statement_timeout` caps runaway queries.
AST validation + a view allowlist (app/services/ai/sql_guard.py) gates which
views can be read, before any SQL reaches here.
"""

from sqlalchemy import URL, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings

STATEMENT_TIMEOUT_MS = 5000

_ro_engine: AsyncEngine | None = None


def _readonly_url() -> URL:
    """Derive the read-only connection URL from DATABASE_URL, swapping creds."""
    settings = get_settings()
    return make_url(settings.database_url).set(
        username=settings.ai_db_user, password=settings.ai_db_password
    )


def get_readonly_engine() -> AsyncEngine:
    global _ro_engine
    if _ro_engine is None:
        kwargs: dict = {}
        if get_settings().environment == "test":
            kwargs["poolclass"] = NullPool
        _ro_engine = create_async_engine(_readonly_url(), **kwargs)
    return _ro_engine


async def run_readonly_query(sql: str) -> list[dict]:
    """Execute already-validated SELECT SQL under read-only + timeout guards."""
    engine = get_readonly_engine()
    async with engine.connect() as conn:
        await conn.exec_driver_sql(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
        await conn.exec_driver_sql("SET default_transaction_read_only = on")
        result = await conn.execute(text(sql))
        rows = [dict(row._mapping) for row in result]
    return rows
