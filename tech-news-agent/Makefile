.PHONY: install test lint format check run pipeline

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
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8300

pipeline:
	curl -X POST http://localhost:8300/internal/run-pipeline
