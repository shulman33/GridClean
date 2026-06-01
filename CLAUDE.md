# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

GridClean computes **gCO₂/kWh for the electricity grid serving a ZIP code, right now**, by fusing two datasets that can't answer the question alone: **EIA-930** (live hourly fuel mix per balancing authority, no emissions) × **EPA eGRID** (CO₂ emission factors per fuel, no live data). On top sits a small AI layer (guardrailed text-to-SQL, ETS forecasting, compute-then-narrate insights). FastAPI + Postgres/TimescaleDB + Redis. Python 3.12, async throughout.

Read `README.md` for the full pitch and `docs/SPEC.md` for the data model and formulas (referenced by `§` numbers in code comments).

## Commands

```bash
make up                  # start Postgres (host port 5433) + Redis via docker compose
make install             # pip install -e ".[dev]"  (do this in an activated .venv)
make migrate             # alembic upgrade head
python -m app.manage seed                 # load reference data (regions, factors, ZIP crosswalk)
python -m app.manage ingest --hours 504   # fetch EIA-930 + recompute intensity (~21d; forecaster needs this much)
make dev                 # uvicorn with reload → http://localhost:8000/app/

make test                # pytest -q  (needs DB + Redis up)
make lint                # ruff check .
make fmt                 # ruff check --fix .
pytest tests/test_ai.py::test_name   # run a single test
make revision m="msg"    # alembic autogenerate migration
python -m app.manage compute            # recompute intensity from already-stored generation
python -m app.manage apikey "Name" --limit 240   # mint an API key (printed once)
python -m app.eval.run   # text-to-SQL eval (execution-match scoring)
```

**Port gotcha:** docker-compose maps Postgres to host **5433** (avoids clashing with a local 5432). For host runs `DATABASE_URL` must point at `localhost:5433`; the `api` container talks to `db:5432` internally.

## Architecture

**Request path:** `app/main.py` → `app/middleware.py` (request ID + timing + structured JSON log on every request) → `app/api/v1/router.py` (mounts `health`, `regions`, `carbon`, `meta`, `ai` under `/v1`). The `/app` static demo (`frontend/`) is mounted last so it can't shadow `/v1`. Docs at `/scalar` and `/docs`.

**Three layers, kept separate:**
- `app/api/v1/*` — thin route handlers. Cross-cutting concerns are applied here via deps/helpers: `enforce_rate_limit` (Redis, per-IP or per-key), `cached_json` (ETag + Cache-Control → 304), auth.
- `app/services/*` — all business logic. `carbon.py` is the core fusion calc; `queries.py` builds the `/now /history /compare /savings` responses; `forecast.py` is statsmodels ETS; `ingest.py`/`eia.py` are the ETL; `ai/` is the AI layer.
- `app/models/*` (SQLAlchemy ORM) + `app/db/session.py` (async engine/session). `app/schemas.py` holds Pydantic response models.

**The fusion (`app/services/carbon.py`):** `gCO₂/kWh = (Σ mwh[fuel]·lb_co2_per_mwh[fuel])·453.592 / (Σ mwh[fuel]·1000)`. The headline data-engineering problem is **geography reconciliation** — EIA reports by balancing authority, eGRID by subregion, and they don't align 1:1. The BA↔subregion mapping carries a `mapping_confidence` flag (`exact`/`dominant`/`approximate`) that is surfaced in every response rather than hidden. Don't "fix" this by dropping the flag.

**AI text-to-SQL (`app/services/ai/`) — the prompt is never the protection; defense is layered in the DB:**
1. `llm.py` / `text_to_sql.py` — Claude emits SQL via a **forced tool call** (structured, never prose), schema + few-shots prompt-cached. `answer_question` does generate → validate → execute with **one repair retry** (DB error fed back to the model).
2. `sql_guard.py` — sqlglot **AST validation**: must be exactly one read-only SELECT/UNION, referencing only the curated `ai_*` views (allowlist: `ai_carbon_intensity`, `ai_regions`, `ai_fuel_generation`), with an enforced LIMIT.
3. `db/readonly.py` — executes as a dedicated **`gridclean_ro` Postgres role** (created by the Phase-4 migration) with SELECT on the `ai_*` views only, plus per-connection `default_transaction_read_only` and `statement_timeout`. It cannot read base tables or write.

`insights.py` uses **compute-then-narrate**: stats (trends, min/max, renewable↔intensity correlation) are computed in NumPy/pandas; the LLM only narrates the numbers so it can't fabricate figures. Preserve this split when editing.

## Conventions

- **Async everywhere.** Services take an `AsyncSession`; routes use `Depends(get_session)`. CLI entrypoints in `app/manage.py` wrap calls in `asyncio.run`.
- **Migrations are ordered by phase** (`alembic/versions/*phase{N}*`) and the read-only role + `ai_*` views are created by the Phase-4 migration — not in app code. New schema goes through `make revision`.
- **Config** is a single `app/config.py` `Settings` (pydantic-settings, `.env`). `get_settings()` is `lru_cache`d. `ENVIRONMENT=test` switches DB engines to `NullPool`.
- **Tests** (`tests/conftest.py`) run against real Postgres + Redis, isolate on Redis DB index 15, and flush per test. AI tests inject a **fake generator/narrator** so CI makes no live model calls — but the real guard + read-only execution path still run against synthetic data. Keep that pattern: never add live model calls to tests.
- Ruff: line-length 100, rules `E,F,I,UP,B` (B008 ignored — FastAPI callable defaults). `alembic/versions` is excluded from lint; don't hand-edit lint-clean migrations.
- The AI model is `claude-opus-4-8` (set `AI_MODEL=claude-sonnet-4-6` to cut cost).
