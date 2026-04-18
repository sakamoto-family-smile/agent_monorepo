.PHONY: install sync run test lint format check clean help

PYTHON ?= uv run
APP_PORT ?= 8001

help:
	@echo "Targets:"
	@echo "  install   - sync dependencies (incl. dev)"
	@echo "  sync      - sync dependencies (prod only)"
	@echo "  run       - run the API on :$(APP_PORT) with reload"
	@echo "  test      - run pytest"
	@echo "  lint      - ruff check"
	@echo "  format    - ruff format + fix"
	@echo "  check     - lint + tests"
	@echo "  clean     - remove caches"

install:
	uv sync

sync:
	uv sync --no-dev

run:
	$(PYTHON) uvicorn main:app --host 127.0.0.1 --port $(APP_PORT) --app-dir app --reload

test:
	$(PYTHON) pytest tests/ -v

lint:
	$(PYTHON) ruff check app tests

format:
	$(PYTHON) ruff check --fix app tests
	$(PYTHON) ruff format app tests

check: lint test

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache **/__pycache__
