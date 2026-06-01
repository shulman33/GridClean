.PHONY: up down install lint test migrate revision dev fmt seed ingest compute

# Start Postgres (host port 5433) + Redis
up:
	docker compose up -d db redis

down:
	docker compose down

install:
	pip install -e ".[dev]"

lint:
	ruff check .

fmt:
	ruff check --fix .

test:
	pytest -q

# Apply migrations to head
migrate:
	alembic upgrade head

# Generate a new autogenerate migration: make revision m="add regions table"
revision:
	alembic revision --autogenerate -m "$(m)"

# Load seed reference data (regions, emission factors, ZIP crosswalk)
seed:
	python -m app.manage seed

# Fetch EIA-930 generation + recompute carbon intensity: make ingest hours=48
ingest:
	python -m app.manage ingest --hours $(or $(hours),24)

# Recompute carbon intensity from already-stored generation
compute:
	python -m app.manage compute

# Run the API locally with reload (expects `make up` first)
dev:
	uvicorn app.main:app --reload --port 8000
