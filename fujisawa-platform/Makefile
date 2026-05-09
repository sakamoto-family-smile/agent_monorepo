.PHONY: install install-phase1 test lint format check help

install:
	uv sync

install-phase1:
	uv sync --extra phase1

test:
	uv run pytest -v

lint:
	uv run ruff check fujisawa_platform tests

format:
	uv run ruff format fujisawa_platform tests
	uv run ruff check --fix fujisawa_platform tests

check: lint test

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install         Install base dependencies (no extras)"
	@echo "  install-phase1  Install Phase 1 deps (+ resolver extras)"
	@echo "  test            Run pytest"
	@echo "  lint            Run ruff check"
	@echo "  format          Run ruff format + auto-fix"
	@echo "  check           lint + test"
