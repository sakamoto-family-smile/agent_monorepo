.PHONY: install install-gcp phoenix-up phoenix-down demo dbt-run dbt-test dbt-parse-bq dbt-run-bq dbt-test-bq etl gcp-bootstrap test lint format check clean help

PYTHON ?= uv run

help:
	@echo "Targets (local / DuckDB):"
	@echo "  install        - sync dependencies (incl. dev)"
	@echo "  phoenix-up     - start Phoenix (Docker) on :6006"
	@echo "  phoenix-down   - stop Phoenix"
	@echo "  demo           - emit demo events to ./data/raw/"
	@echo "  dbt-run        - run dbt models (DuckDB target)"
	@echo "  dbt-test       - run dbt tests (DuckDB target)"
	@echo "  etl            - demo + dbt run + dbt test (all-in-one)"
	@echo ""
	@echo "Targets (gcp / BigQuery, requires [gcp] extra):"
	@echo "  install-gcp    - sync deps with [gcp] extra (dbt-bigquery 等)"
	@echo "  gcp-bootstrap  - create BQ datasets + external table over GCS (idempotent)"
	@echo "  dbt-parse-bq   - dbt parse against gcp target (no DB connection)"
	@echo "  dbt-run-bq     - dbt run against gcp target (BigQuery)"
	@echo "  dbt-test-bq    - dbt test against gcp target"
	@echo ""
	@echo "Targets (other):"
	@echo "  test           - run pytest"
	@echo "  lint           - ruff check"
	@echo "  format         - ruff --fix + format"
	@echo "  check          - lint + test"
	@echo "  clean          - remove caches and local artifacts"

install:
	uv sync

install-gcp:
	uv sync --extra gcp

phoenix-up:
	docker compose up -d phoenix

phoenix-down:
	docker compose down

demo:
	$(PYTHON) python scripts/demo_emit.py --count $${DEMO_COUNT:-20}

dbt-run:
	cd dbt && $(PYTHON) dbt run --profiles-dir . --project-dir .

dbt-test:
	cd dbt && $(PYTHON) dbt test --profiles-dir . --project-dir .

etl:
	bash scripts/run_etl.sh

gcp-bootstrap:
	bash scripts/gcp_bootstrap.sh

dbt-parse-bq:
	cd dbt && $(PYTHON) dbt parse --profiles-dir . --project-dir . --target gcp

dbt-run-bq:
	cd dbt && $(PYTHON) dbt run --profiles-dir . --project-dir . --target gcp

dbt-test-bq:
	cd dbt && $(PYTHON) dbt test --profiles-dir . --project-dir . --target gcp

test:
	$(PYTHON) pytest tests/ -v

lint:
	$(PYTHON) ruff check app tests scripts

format:
	$(PYTHON) ruff check --fix app tests scripts
	$(PYTHON) ruff format app tests scripts

check: lint test

clean:
	rm -rf .pytest_cache .ruff_cache dbt/target dbt/logs
	rm -rf data/raw data/uploaded data/dead_letter data/payloads data/*.duckdb data/*.duckdb.wal
	find . -type d -name __pycache__ -exec rm -rf {} +
