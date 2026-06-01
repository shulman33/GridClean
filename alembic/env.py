"""Alembic migration environment.

Uses a synchronous psycopg driver for migrations (derived from the app's
async DATABASE_URL) and pulls model metadata from the declarative Base so
autogenerate works as models are added in later phases.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

import app.models  # noqa: F401 — registers all models on Base.metadata
from alembic import context
from app.config import get_settings
from app.db.session import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Alembic runs migrations synchronously; convert the async URL to a sync one.
# Two things change vs. the app's async URL: the driver (asyncpg → psycopg) and
# the SSL query param. asyncpg spells it `ssl=require`; psycopg/libpq spells it
# `sslmode=require` and errors on a bare `ssl` option — so translate it here, or
# managed hosts (Neon/RDS) that require SSL fail the release migration.
sync_url = make_url(get_settings().database_url).set(drivername="postgresql+psycopg")
query = dict(sync_url.query)
if "ssl" in query:
    query["sslmode"] = query.pop("ssl")
sync_url = sync_url.set(query=query)
config.set_main_option("sqlalchemy.url", sync_url.render_as_string(hide_password=False))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
