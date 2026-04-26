.PHONY: install test lint format check run migrate migrate-down migrate-revision \
        docker-build docker-run docker-shell cloudbuild-submit deploy-cloud-run \
        tf-init tf-fmt tf-fmt-check tf-validate tf-plan tf-apply tf-output-env \
        bootstrap-gcp help

IMAGE_NAME ?= piyolog-analytics
IMAGE_TAG ?= local
# build context = リポジトリルート (path dep `../analytics-platform` を解決するため)
REPO_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || cd .. && pwd)

# Terraform CLI workdir。`make tf-* TF_DIR=...` で上書き可能。
TF_DIR ?= terraform
# `make tf-output-env` の出力先 (deploy_cloud_run.sh が読む env)
TF_ENV_FILE ?= .env.deploy

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

# ---- Docker / Cloud Run ----
# build context は repo root (path dep `../analytics-platform` を解決するため)。
# `make docker-build` は自動的に repo root から build を打つ。
docker-build:
	cd $(REPO_ROOT) && DOCKER_BUILDKIT=1 docker build \
	  -f piyolog-analytics/Dockerfile \
	  -t $(IMAGE_NAME):$(IMAGE_TAG) \
	  .

# ローカルで起動して LINE webhook を ngrok で公開する用。
# DATABASE_URL を渡さないと SQLite ファイルベース (data/piyolog.db) で動く。
docker-run:
	docker run --rm -p 8200:8200 \
	  -e LINE_CHANNEL_SECRET \
	  -e LINE_CHANNEL_ACCESS_TOKEN \
	  -e FAMILY_USER_IDS \
	  -e FAMILY_ID \
	  -e APP_ENV \
	  -e DATABASE_URL \
	  -e DB_AUTO_CREATE \
	  $(IMAGE_NAME):$(IMAGE_TAG)

docker-shell:
	docker run --rm -it --entrypoint sh $(IMAGE_NAME):$(IMAGE_TAG)

# Cloud Build 経由で Artifact Registry に push。
# 例: PIYOLOG_GCP_PROJECT=youyaku-ai PIYOLOG_AR_LOCATION=us-central1 make cloudbuild-submit
cloudbuild-submit:
	cd $(REPO_ROOT) && gcloud builds submit \
	  --project=$${PIYOLOG_GCP_PROJECT:?set PIYOLOG_GCP_PROJECT} \
	  --config=piyolog-analytics/cloudbuild.yaml \
	  --substitutions=_LOCATION=$${PIYOLOG_AR_LOCATION:-us-central1},_REPO=$${PIYOLOG_AR_REPO:-piyolog-analytics} \
	  .

# Cloud Run service にデプロイ。詳細 env は scripts/deploy_cloud_run.sh のヘッダ参照。
deploy-cloud-run:
	bash scripts/deploy_cloud_run.sh

# ---- B4 (実機開通) ----
# `bootstrap-gcp` は GCP project の最初の準備 (state bucket + API enable) を行う。
# 必須 env: PIYOLOG_GCP_PROJECT
# 実行後、TF apply → image push → Cloud Run deploy → LINE Webhook 登録 の順で進む。
# 詳細は README §0.5.2 「開通手順 (B4)」を参照。
bootstrap-gcp:
	bash scripts/bootstrap_gcp.sh

# ---- Terraform IaC (Step B3) ----
# Cloud SQL / Secret Manager / sa-piyolog / Artifact Registry を Terraform で管理。
# 詳細手順は terraform/README.md を参照。
# 初回は state バケットを手動作成し、backend.tf と terraform.tfvars を準備してから
# `make tf-init` → `make tf-plan` → `make tf-apply`。
tf-init:
	cd $(TF_DIR) && terraform init -input=false

tf-fmt:
	cd $(TF_DIR) && terraform fmt -recursive

tf-fmt-check:
	cd $(TF_DIR) && terraform fmt -check -recursive -diff

# 認証不要 (-backend=false なので state も触らない)
tf-validate:
	cd $(TF_DIR) && terraform init -backend=false -input=false -no-color >/dev/null && terraform validate -no-color

tf-plan:
	cd $(TF_DIR) && terraform plan -out=tfplan -input=false

tf-apply:
	cd $(TF_DIR) && terraform apply -input=false tfplan

# `terraform output env_for_deploy` を `.env.deploy` に書き出す。
# `set -a; source .env.deploy; set +a` で deploy_cloud_run.sh に流せる。
tf-output-env:
	cd $(TF_DIR) && terraform output -json env_for_deploy \
	  | jq -r 'to_entries[] | "\(.key)=\(.value)"' \
	  > ../$(TF_ENV_FILE)
	@echo "[tf-output-env] wrote $(TF_ENV_FILE)"

help:
	@echo "Targets:"
	@echo "  install              - uv sync"
	@echo "  test / lint / format / check"
	@echo "  run                  - 直接 uvicorn でローカル起動"
	@echo ""
	@echo "Targets (DB / Alembic):"
	@echo "  migrate              - alembic upgrade head"
	@echo "  migrate-down         - alembic downgrade -1"
	@echo "  migrate-revision MSG=... - 新規 migration"
	@echo ""
	@echo "Targets (Docker / Cloud Run、Step B2):"
	@echo "  docker-build         - $(IMAGE_NAME):$(IMAGE_TAG) を build (context = repo root)"
	@echo "  docker-run           - container 起動 (ローカル + env で接続情報を渡す)"
	@echo "  docker-shell         - container 内 shell でデバッグ"
	@echo "  cloudbuild-submit    - Cloud Build → Artifact Registry に push"
	@echo "  deploy-cloud-run     - Cloud Run service にデプロイ (要 secrets / Cloud SQL)"
	@echo ""
	@echo "Targets (Terraform IaC、Step B3):"
	@echo "  tf-init              - terraform init"
	@echo "  tf-fmt / tf-fmt-check - terraform fmt"
	@echo "  tf-validate          - terraform init -backend=false + validate (no creds)"
	@echo "  tf-plan / tf-apply   - 通常の plan / apply (要 backend.tf + tfvars)"
	@echo "  tf-output-env        - terraform output env_for_deploy -> $(TF_ENV_FILE)"
