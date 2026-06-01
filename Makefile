.PHONY: up down install lint test migrate revision dev fmt

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

# Run the API locally with reload (expects `make up` first)
dev:
	uvicorn app.main:app --reload --port 8000
