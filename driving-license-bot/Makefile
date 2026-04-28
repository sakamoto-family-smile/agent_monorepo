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

.PHONY: help install lint format test check run docker-build docker-run \
	tf-init tf-plan tf-apply tf-destroy tf-fmt tf-validate tf-output-wif \
	bootstrap teardown teardown-app image-build _require_project show-project

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
	docker run --rm -p 8080:8080 \
		-e LINE_CHANNEL_SECRET="$$LINE_CHANNEL_SECRET" \
		-e LINE_CHANNEL_ACCESS_TOKEN="$$LINE_CHANNEL_ACCESS_TOKEN" \
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

tf-output-wif:  ## WIF setup 用に GitHub repo Variables にコピペする値を表示
	@cd $(TF_DIR) && terraform output -json wif_setup_summary 2>/dev/null \
		| jq -r 'to_entries[] | "\(.key)=\(.value)"' \
		|| echo "wif outputs not available. enable_wif=true で apply してください。"

image-build: _require_project  ## Cloud Build で image を build & push（リポジトリルートから実行）
	cd .. && gcloud builds submit \
		--project=$(GOOGLE_CLOUD_PROJECT) \
		--config=driving-license-bot/cloudbuild.yaml \
		--substitutions=_LOCATION=$(REGION),_REPO=$(ARTIFACT_REPO) \
		.

teardown-app: _require_project  ## 課金リソースのみ削除（WIF / tfstate を残し、CI plan は動作継続）
	GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) ./scripts/teardown_app.sh

teardown: _require_project  ## driving-license-bot のリソース一括削除（WIF も含む完全削除）
	GOOGLE_CLOUD_PROJECT=$(GOOGLE_CLOUD_PROJECT) ./scripts/teardown.sh
