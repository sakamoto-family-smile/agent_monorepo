.PHONY: install test lint format check run migrate migrate-down migrate-revision

install:
	uv sync

test:
	uv run pytest -v

lint:
	uv run ruff check app tests

format:
	uv run ruff format app tests
	uv run ruff check --fix app tests

check: lint test

run:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8200

# ---- DB migrations (Alembic) ----
# DATABASE_URL or PIYOLOG_DB_PATH を env で渡す。
# 例: DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/piyolog make migrate
migrate:
	uv run alembic upgrade head

migrate-down:
	uv run alembic downgrade -1

# 例: make migrate-revision MSG="add column foo"
migrate-revision:
	uv run alembic revision --autogenerate -m "$${MSG:?set MSG=...}"
