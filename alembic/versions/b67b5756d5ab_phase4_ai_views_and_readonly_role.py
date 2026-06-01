"""phase4 ai views and readonly role

Creates the curated read-only views the AI text-to-SQL layer may query, plus a
dedicated `gridclean_ro` login role with SELECT only on those views (no access
to base tables) and role-level read-only + statement_timeout defaults. This is
the DB-level guardrail behind the AI layer — see app/db/readonly.py.

Revision ID: b67b5756d5ab
Revises: 2dcb5d78d48e
Create Date: 2026-06-01 12:13:28.712355
"""
from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = 'b67b5756d5ab'
down_revision: str | None = '2dcb5d78d48e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEWS = ("ai_carbon_intensity", "ai_regions", "ai_fuel_generation")


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW ai_carbon_intensity AS
        SELECT c.region_code, r.name AS region_name, r.egrid_subregion, c.period,
               c.gco2_per_kwh, c.total_mwh, c.renewable_share, c.carbon_free_share
        FROM carbon_intensity_hourly c
        JOIN regions r ON r.code = c.region_code
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW ai_regions AS
        SELECT code, name, egrid_subregion, mapping_confidence, timezone
        FROM regions
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW ai_fuel_generation AS
        SELECT g.region_code, r.name AS region_name, g.period,
               g.fuel_code, f.fuel_name, g.mwh
        FROM generation_hourly g
        JOIN regions r ON r.code = g.region_code
        LEFT JOIN emission_factors f
          ON f.fuel_code = g.fuel_code AND f.version = 'v1-seed'
        """
    )

    settings = get_settings()
    pw = settings.ai_db_password.replace("'", "''")
    op.execute(
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{settings.ai_db_user}') THEN
            CREATE ROLE {settings.ai_db_user} LOGIN PASSWORD '{pw}';
          END IF;
        END $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {settings.ai_db_user}")
    op.execute(
        f"GRANT SELECT ON {', '.join(VIEWS)} TO {settings.ai_db_user}"
    )
    op.execute(f"ALTER ROLE {settings.ai_db_user} SET statement_timeout = '5000ms'")
    op.execute(
        f"ALTER ROLE {settings.ai_db_user} SET default_transaction_read_only = on"
    )


def downgrade() -> None:
    settings = get_settings()
    for view in VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {view}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {settings.ai_db_user}")
    op.execute(f"DROP ROLE IF EXISTS {settings.ai_db_user}")
