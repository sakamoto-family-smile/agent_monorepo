.PHONY: install install-gcp phoenix-up phoenix-down demo dbt-run dbt-test dbt-parse-bq dbt-run-bq dbt-test-bq etl gcp-bootstrap docker-build docker-parse docker-run docker-test docker-shell deploy-orchestration trigger-workflow test lint format check clean help

IMAGE_NAME ?= analytics-platform-dbt
IMAGE_TAG ?= local

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
	@echo "Targets (docker / Cloud Run Job image):"
	@echo "  docker-build   - build $(IMAGE_NAME):$(IMAGE_TAG) (multi-stage)"
	@echo "  docker-parse   - run \`dbt parse\` inside the image (smoke)"
	@echo "  docker-run     - run \`dbt run\` inside the image (requires gcloud ADC mount)"
	@echo "  docker-test    - run \`dbt test\` inside the image"
	@echo "  docker-shell   - drop into bash for debugging"
	@echo ""
	@echo "Targets (orchestration / Cloud Workflows + Scheduler):"
	@echo "  deploy-orchestration - deploy Cloud Workflow + Scheduler (idempotent)"
	@echo "  trigger-workflow     - manually trigger the deployed Workflow"
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

# ---- Docker / Cloud Run Job ----
# `make docker-build` でイメージを build し、`make docker-parse` で軽い疎通確認、
# `make docker-run` / `make docker-test` で実 BigQuery に対してジョブを流せる。
# ローカルから実行するときは `~/.config/gcloud` を mount して ADC を渡す。
DOCKER_RUN_BASE = docker run --rm \
  -v $${HOME}/.config/gcloud:/home/runner/.config/gcloud:ro \
  -e ANALYTICS_BQ_PROJECT \
  -e ANALYTICS_BQ_LOCATION \
  -e ANALYTICS_BQ_DEFAULT_DATASET \
  -e ANALYTICS_BQ_RAW_DATASET \
  -e ANALYTICS_BQ_RAW_TABLE \
  -e ANALYTICS_GCS_BUCKET \
  -e DBT_TARGET=$${DBT_TARGET:-gcp} \
  $(IMAGE_NAME):$(IMAGE_TAG)

docker-build:
	DOCKER_BUILDKIT=1 docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

docker-parse:
	$(DOCKER_RUN_BASE) parse

docker-run:
	$(DOCKER_RUN_BASE) run

docker-test:
	$(DOCKER_RUN_BASE) test

docker-shell:
	$(DOCKER_RUN_BASE) shell

# ---- Orchestration (Cloud Workflows + Cloud Scheduler) ----
# Step 8: 既存の Cloud Run Job を Cloud Workflows で起動し、Scheduler で定期実行する。
# `deploy-orchestration` は Workflow と Scheduler を同時に create/update する idempotent コマンド。
# 必須 env: ANALYTICS_GCP_PROJECT。詳細は scripts/deploy_orchestration.sh のヘッダ参照。
deploy-orchestration:
	bash scripts/deploy_orchestration.sh

trigger-workflow:
	gcloud workflows execute $${ANALYTICS_WORKFLOW_NAME:-analytics-platform-dbt-pipeline} \
	  --project=$${ANALYTICS_GCP_PROJECT} \
	  --location=$${ANALYTICS_WORKFLOW_LOCATION:-us-central1} \
	  --data='{"project":"$${ANALYTICS_GCP_PROJECT}","location":"$${ANALYTICS_DBT_JOB_LOCATION:-us-central1}","job_name":"$${ANALYTICS_DBT_JOB_NAME:-analytics-platform-dbt}","dbt_command":"$${ANALYTICS_DBT_COMMAND:-run-and-test}"}'

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
