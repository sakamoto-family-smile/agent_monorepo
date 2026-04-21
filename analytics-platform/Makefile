.PHONY: install phoenix-up phoenix-down demo dbt-run dbt-test etl test lint format check clean help

PYTHON ?= uv run

help:
	@echo "Targets:"
	@echo "  install     - sync dependencies (incl. dev)"
	@echo "  phoenix-up  - start Phoenix (Docker) on :6006"
	@echo "  phoenix-down- stop Phoenix"
	@echo "  demo        - emit demo events to ./data/raw/"
	@echo "  dbt-run     - run dbt models (DuckDB)"
	@echo "  dbt-test    - run dbt tests"
	@echo "  etl         - demo + dbt run + dbt test (all-in-one)"
	@echo "  test        - run pytest"
	@echo "  lint        - ruff check"
	@echo "  format      - ruff --fix + format"
	@echo "  check       - lint + test"
	@echo "  clean       - remove caches and local artifacts"

install:
	uv sync

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
