# GridClean

> Live carbon intensity of electricity, by location — a data-fusion API with a guardrailed AI layer.

GridClean computes **grams of CO₂ per kWh for the electricity grid serving a given ZIP code, right now**, and forecasts the cleanest hours ahead. It does this by fusing two datasets that can't answer the question alone:

- **EIA-930** — the live fuel mix of each regional grid (coal vs. gas vs. wind vs. solar, hourly). No emissions data.
- **EPA eGRID** — emission factors per fuel type (lb CO₂ / MWh). No live data.

Multiply them and you get a live carbon-intensity number that neither source publishes — the metric companies like WattTime sell commercially.

On top sits a small, deliberately well-engineered AI layer: guardrailed natural-language querying, LLM-narrated insights over computed statistics, and a 24-hour forecast with honest confidence intervals.

## Status

🚧 Early development. See [`docs/SPEC.md`](docs/SPEC.md) for the full technical specification and build plan.

## Stack

FastAPI · Postgres + TimescaleDB + pgvector · Redis · Anthropic Claude · Prophet/NeuralProphet · Scalar docs · deployed on Render/Railway + Neon.

## Quickstart (local dev)

```bash
# 1. Start Postgres (host port 5433) + Redis
make up                 # or: docker compose up -d db redis

# 2. Create a virtualenv and install
python3 -m venv .venv && source .venv/bin/activate
make install            # pip install -e ".[dev]"

# 3. Configure env
cp .env.example .env    # then edit DATABASE_URL host port to 5433 for local runs

# 4. Apply migrations and run
make migrate            # alembic upgrade head
make dev                # uvicorn on :8000  →  http://localhost:8000/docs
```

> **Note:** docker-compose maps Postgres to host port **5433** (to avoid clashing
> with a local Postgres on 5432). The `api` container talks to `db:5432` internally,
> so set `DATABASE_URL=...@localhost:5433/...` only for runs from your host.

Run tests and lint:

```bash
make test    # pytest
make lint    # ruff
```

## Attribution

- Electricity generation: U.S. Energy Information Administration (EIA-930)
- Emission factors: U.S. EPA eGRID
- ZIP/region mapping: U.S. EPA Power Profiler / U.S. Census
