.PHONY: install install-pgvector install-vertex install-pdf install-all test lint format check help

install:
	uv sync

install-pgvector:
	uv sync --extra pgvector

install-vertex:
	uv sync --extra vertex

install-pdf:
	uv sync --extra pdf

install-all:
	uv sync --extra pgvector --extra vertex --extra pdf

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
	@echo "  install            Install base + resolver (default)"
	@echo "  install-pgvector   Add pgvector backend (Phase 4 ETL のみ)"
	@echo "  install-vertex     Add Vertex AI embedding (本番のみ、テストは Mock)"
	@echo "  install-pdf        Add Docling (PDF 構造化、ETL Job のみ)"
	@echo "  install-all        全 optional deps を入れる"
	@echo "  test               Run pytest"
	@echo "  lint               Run ruff check"
	@echo "  format             Run ruff format + auto-fix"
	@echo "  check              lint + test"
