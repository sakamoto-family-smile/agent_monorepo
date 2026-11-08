SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

UV ?= uv
IMAGE_NAME ?= driving-license-bot
IMAGE_TAG ?= local
TF_DIR ?= terraform
REGION ?= asia-northeast1
ARTIFACT_REPO ?= driving-license-bot

# GCP プロジェクト ID。優先順:
#   1. 明示的に指定された GOOGLE_CLOUD_PROJECT env
#   2. gcloud config get-value project
# どちらも取得できなければターゲット実行時に :require_project で失敗する。
GOOGLE_CLOUD_PROJECT ?= $(shell gcloud config get-value project 2>/dev/null)

CLOUDSQL_INSTANCE ?= driving-license-bot-pg
CLOUDSQL_CONNECTION ?= $(GOOGLE_CLOUD_PROJECT):$(REGION):$(CLOUDSQL_INSTANCE)

.PHONY: help install lint format test check run docker-build docker-run \
	tf-init tf-plan tf-apply tf-destroy tf-fmt tf-validate tf-output-wif \
	tf-plan-deployer tf-apply-deployer _tf-init-deployer \
	bootstrap teardown teardown-app image-build secrets-push \
	cloudsql-proxy cloudsql-init cloudsql-verify \
	vertex-verify batch-trigger workflow-trigger \
	backup restore \
	_require_project show-project

help:  ## このヘルプを表示
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

install:  ## 依存をインストール（uv sync）
	$(UV) sync --extra gcs

lint:  ## ruff でチェック
	$(UV) run ruff check app tests

format:  ## ruff で整形
	$(UV) run ruff format app tests
	$(UV) run ruff check --fix app tests

test:  ## pytest 実行
	$(UV) run pytest -q

check: lint test  ## lint + test

run:  ## ローカル起動（要 .env または環境変数）
	$(UV) run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

docker-build:  ## Docker image を build（リポジトリルートから実行する）
	cd .. && DOCKER_BUILDKIT=1 docker build \
		-f driving-license-bot/Dockerfile \
		-t $(IMAGE_NAME):$(IMAGE_TAG) \
		.

docker-run:  ## Docker image をローカル起動
	@# 値は argv に載せず (ps で見える)、変数名だけ渡して現在の環境から引き継がせる
	docker run --rm -p 8080:8080 \
		-e LINE_CHANNEL_SECRET \
		-e LINE_CHANNEL_ACCESS_TOKEN \
		$(IMAGE_NAME):$(IMAGE_TAG)

# ---- GCP デプロイ系（Terraform 主導） ----

# 明示 env も gcloud 設定もない場合のガード
_require_project:
	@if [ -z "$(GOOGLE_CLOUD_PROJECT)" ]; then \
		echo "ERROR: GOOGLE_CLOUD_PROJECT が解決できません。"; \
		echo "  対応: 'gcloud config set project <PROJECT_ID>' か"; \
		echo "        'GOOGLE_CLOUD_PROJECT=<PROJECT_ID> make ...' を指定"; \
		exit 1; \
	fi

show-project:  ## 現在使用される GCP プロジェクトを表示
	@echo "GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT)"

bootstrap: _require_project  ## GCP プロジェクト初回ブートストラップ（tfstate バケット + base API）
	GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) ./scripts/bootstrap_gcp.sh

tf-init:  ## terraform init
	cd $(TF_DIR) && terraform init -upgrade

tf-fmt:  ## terraform fmt
	cd $(TF_DIR) && terraform fmt -recursive

tf-validate:  ## terraform validate
	cd $(TF_DIR) && terraform validate

tf-plan:  ## terraform plan
	cd $(TF_DIR) && terraform plan

tf-apply:  ## terraform apply
	cd $(TF_DIR) && terraform apply

tf-destroy:  ## terraform destroy（確認あり）
	cd $(TF_DIR) && terraform destroy

# 自動デプロイ用 SA (terraform/deploy.tf) と WIF Provider の属性だけを apply する。
# 全体の apply は tfvars と本番の差分 (min instances・削除保護など) まで巻き込むので使わない。
DEPLOYER_TARGETS := \
	-target=google_iam_workload_identity_pool_provider.github \
	-target=google_service_account.deployer \
	-target=google_service_account_iam_member.deployer_wif \
	-target=google_artifact_registry_repository_iam_member.deployer_push \
	-target=google_cloud_run_v2_service_iam_member.deployer_service \
	-target=google_cloud_run_v2_job_iam_member.deployer_job \
	-target=google_project_iam_member.deployer_run_viewer \
	-target=google_service_account_iam_member.deployer_act_as
DEPLOYER_VARS = -var project_id=$(GOOGLE_CLOUD_PROJECT) -var enable_wif=true
TFSTATE_BUCKET ?= $(GOOGLE_CLOUD_PROJECT)-driving-license-bot-tfstate

_tf-init-deployer: _require_project
	@cd $(TF_DIR) && if [ ! -f backend.tf ]; then \
		printf 'terraform {\n  backend "gcs" {\n    bucket = "%s"\n    prefix = "terraform/state"\n  }\n}\n' "$(TFSTATE_BUCKET)" > backend.tf; \
		echo "[deployer] backend.tf を作成 (bucket=$(TFSTATE_BUCKET))"; \
	fi
	cd $(TF_DIR) && GOOGLE_OAUTH_ACCESS_TOKEN=$$(gcloud auth print-access-token) terraform init -input=false

tf-plan-deployer: _tf-init-deployer  ## 自動デプロイ用 SA だけの plan
	cd $(TF_DIR) && GOOGLE_OAUTH_ACCESS_TOKEN=$$(gcloud auth print-access-token) \
		terraform plan -input=false $(DEPLOYER_TARGETS) $(DEPLOYER_VARS)

tf-apply-deployer: _tf-init-deployer  ## 自動デプロイ用 SA だけを apply（確認あり）
	cd $(TF_DIR) && GOOGLE_OAUTH_ACCESS_TOKEN=$$(gcloud auth print-access-token) \
		terraform apply -input=false $(DEPLOYER_TARGETS) $(DEPLOYER_VARS)

tf-output-wif:  ## WIF setup 用に GitHub repo Variables にコピペする値を表示
	@cd $(TF_DIR) && GOOGLE_OAUTH_ACCESS_TOKEN=$$(gcloud auth print-access-token) terraform output -json wif_setup_summary 2>/dev/null \
		| jq -r 'to_entries[] | "\(.key)=\(.value)"' \
		|| echo "wif outputs not available. enable_wif=true で apply してください。"

secrets-push: _require_project  ## .env.secrets を読み Secret Manager に値投入（teardown-app では消えない）
	GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) ./scripts/push_line_secrets.sh

image-build: _require_project  ## Cloud Build で image を build & push（リポジトリルートから実行）
	@SHA=$$(git rev-parse --short=7 HEAD 2>/dev/null || echo "manual"); \
	echo "[image-build] _SHA=$$SHA"; \
	cd .. && gcloud builds submit \
		--project=$(GOOGLE_CLOUD_PROJECT) \
		--config=driving-license-bot/cloudbuild.yaml \
		--substitutions=_SHA=$$SHA,_LOCATION=$(REGION),_REPO=$(ARTIFACT_REPO) \
		.

teardown-app: _require_project  ## 課金リソースのみ削除（WIF / tfstate を残し、CI plan は動作継続）
	GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) ./scripts/teardown_app.sh

# ---- Cloud SQL pgvector 系（Phase 2-A2）----

cloudsql-proxy: _require_project  ## Cloud SQL Auth Proxy を foreground 起動（127.0.0.1:5432）
	@echo "[cloudsql-proxy] connecting to $(CLOUDSQL_CONNECTION)"
	@command -v cloud-sql-proxy >/dev/null 2>&1 || { \
		echo "ERROR: cloud-sql-proxy が見つかりません。"; \
		echo "  install: gcloud components install cloud-sql-proxy"; \
		echo "  または: https://cloud.google.com/sql/docs/postgres/sql-proxy#install"; \
		exit 1; \
	}
	cloud-sql-proxy --port=5432 $(CLOUDSQL_CONNECTION)

cloudsql-init: _require_project  ## pgvector extension + questions テーブル + index を投入（要 Auth Proxy 起動）
	GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) \
		$(UV) run --extra pgvector python scripts/init_question_bank_schema.py

cloudsql-verify: _require_project  ## Cloud SQL pgvector の add/find_similar/count smoke（要 Auth Proxy 起動）
	GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) \
		$(UV) run --extra pgvector python scripts/verify_question_bank.py

# ---- Vertex AI 系（Phase 2-B1）----

vertex-verify: _require_project  ## Vertex AI Claude / Gemini / Embedding の到達性 smoke（実コール、< $0.01）
	GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) \
		$(UV) run python scripts/verify_vertex_models.py

# ---- 自動生成バッチ trigger（Phase 2-B2）----

batch-trigger: _require_project  ## Cloud Run Job (driving-license-bot-batch) を即時 1 回実行（テスト用）
	gcloud run jobs execute driving-license-bot-batch \
		--project=$(GOOGLE_CLOUD_PROJECT) \
		--region=$(REGION) \
		--wait

workflow-trigger: _require_project  ## Workflow を手動起動（Scheduler 経由ではなく即時）
	gcloud workflows execute driving-license-bot-generation-pipeline \
		--project=$(GOOGLE_CLOUD_PROJECT) \
		--location=$(REGION) \
		--data='{"project":"$(GOOGLE_CLOUD_PROJECT)","location":"$(REGION)"}'

teardown: _require_project  ## driving-license-bot のリソース一括削除（WIF も含む完全削除）
	GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) ./scripts/teardown.sh

# ---- Backup / Restore (Phase 2-Y1) ----

backup: _require_project  ## Firestore + Cloud SQL を GCS bucket にバックアップ
	GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) ./scripts/backup_data.sh

restore: _require_project  ## 最新 backup を Firestore + Cloud SQL に復元（無ければ skip）
	GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) ./scripts/restore_data.sh
