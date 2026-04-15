################################################################################
# kanie-lab-agent Makefile
#
# 使い方:
#   make dev          - ローカル開発環境を起動
#   make setup-gcp    - GCP 初期セットアップ（初回のみ）
#   make deploy       - 手動デプロイ（Cloud Build をキック）
#   make logs-backend - バックエンドのログを確認
################################################################################

PROJECT_ID ?= $(shell gcloud config get-value project 2>/dev/null)
REGION     ?= us-central1
REGISTRY   := $(REGION)-docker.pkg.dev/$(PROJECT_ID)/kanie-lab

.PHONY: dev dev-down setup-gcp destroy deploy deploy-backend deploy-frontend \
        logs-backend logs-frontend build-backend build-frontend \
        push-backend push-frontend secrets-list help

# ---- ローカル開発 -------------------------------------------------------

dev:
	docker compose up --build

dev-down:
	docker compose down

dev-logs:
	docker compose logs -f

# ---- GCP セットアップ ---------------------------------------------------

setup-gcp:
	@echo "GCP セットアップを実行します (PROJECT_ID=$(PROJECT_ID))"
	bash infra/scripts/setup-gcp.sh

first-deploy:
	@echo "初回デプロイを実行します (PROJECT_ID=$(PROJECT_ID))"
	bash infra/scripts/first-deploy.sh

setup-trigger:
	@if [ -z "$(GITHUB_OWNER)" ] || [ -z "$(GITHUB_REPO)" ]; then \
	  echo "使い方: make setup-trigger GITHUB_OWNER=xxx GITHUB_REPO=yyy"; exit 1; fi
	@source infra/scripts/.firebase-config && \
	gcloud builds triggers create github \
	  --name="kanie-lab-deploy-main" \
	  --repo-name=$(GITHUB_REPO) \
	  --repo-owner=$(GITHUB_OWNER) \
	  --branch-pattern='^main$$' \
	  --build-config=cloudbuild.yaml \
	  --substitutions="_REGION=$(REGION),_BACKEND_SA=kanie-lab-backend@$(PROJECT_ID).iam.gserviceaccount.com,_FRONTEND_SA=kanie-lab-frontend@$(PROJECT_ID).iam.gserviceaccount.com,_FIREBASE_PROJECT_ID=$${FIREBASE_PROJECT_ID},_FIREBASE_API_KEY=$${FIREBASE_API_KEY},_FIREBASE_AUTH_DOMAIN=$${FIREBASE_AUTH_DOMAIN},_FIREBASE_STORAGE_BUCKET=$${FIREBASE_STORAGE_BUCKET},_FIREBASE_MESSAGING_SENDER_ID=$${FIREBASE_MESSAGING_SENDER_ID},_FIREBASE_APP_ID=$${FIREBASE_APP_ID}" \
	  --project=$(PROJECT_ID)

destroy:
	@echo "GCP 環境を削除します (PROJECT_ID=$(PROJECT_ID))"
	bash infra/scripts/teardown-gcp.sh

# ---- イメージビルド & プッシュ ------------------------------------------

build-backend:
	docker build \
	  -f infra/docker/Dockerfile.backend.prod \
	  -t $(REGISTRY)/backend:latest \
	  .

build-frontend:
	@if [ -z "$(NEXT_PUBLIC_FIREBASE_API_KEY)" ]; then \
	  echo "Error: NEXT_PUBLIC_FIREBASE_API_KEY が設定されていません"; exit 1; fi
	docker build \
	  -f infra/docker/Dockerfile.frontend.prod \
	  --build-arg NEXT_PUBLIC_FIREBASE_PROJECT_ID=$(NEXT_PUBLIC_FIREBASE_PROJECT_ID) \
	  --build-arg NEXT_PUBLIC_FIREBASE_API_KEY=$(NEXT_PUBLIC_FIREBASE_API_KEY) \
	  --build-arg NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=$(NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN) \
	  --build-arg NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=$(NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET) \
	  --build-arg NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=$(NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID) \
	  --build-arg NEXT_PUBLIC_FIREBASE_APP_ID=$(NEXT_PUBLIC_FIREBASE_APP_ID) \
	  -t $(REGISTRY)/frontend:latest \
	  .

push-backend: build-backend
	docker push $(REGISTRY)/backend:latest

push-frontend: build-frontend
	docker push $(REGISTRY)/frontend:latest

# ---- Cloud Run デプロイ -------------------------------------------------

deploy-backend: push-backend
	gcloud run deploy kanie-lab-backend \
	  --image=$(REGISTRY)/backend:latest \
	  --region=$(REGION) \
	  --platform=managed \
	  --service-account=kanie-lab-backend@$(PROJECT_ID).iam.gserviceaccount.com \
	  --timeout=3600 \
	  --concurrency=1 \
	  --max-instances=5 \
	  --memory=2Gi \
	  --cpu=2 \
	  --execution-environment=gen2 \
	  --no-allow-unauthenticated \
	  --set-env-vars=APP_ENV=production,FIREBASE_PROJECT_ID=$(PROJECT_ID),GOOGLE_CLOUD_PROJECT=$(PROJECT_ID),WORKSPACE_BASE=/tmp/workspace/users \
	  --set-secrets=ANTHROPIC_API_KEY=anthropic-api-key:latest,BRAVE_API_KEY=brave-api-key:latest,ESTAT_APP_ID=estat-app-id:latest,SEMANTIC_SCHOLAR_API_KEY=semantic-scholar-api-key:latest,FRONTEND_URL=frontend-url:latest \
	  --set-secrets=/tmp/claude_credentials.json=claude-credentials:latest \
	  --project=$(PROJECT_ID)

deploy-frontend: push-frontend
	@BACKEND_URL=$$(gcloud run services describe kanie-lab-backend \
	  --region=$(REGION) --format='value(status.url)' --project=$(PROJECT_ID)); \
	gcloud run deploy kanie-lab-frontend \
	  --image=$(REGISTRY)/frontend:latest \
	  --region=$(REGION) \
	  --platform=managed \
	  --service-account=kanie-lab-frontend@$(PROJECT_ID).iam.gserviceaccount.com \
	  --timeout=60 \
	  --concurrency=80 \
	  --max-instances=10 \
	  --memory=512Mi \
	  --cpu=1 \
	  --allow-unauthenticated \
	  --set-env-vars=NODE_ENV=production,BACKEND_URL=$$BACKEND_URL \
	  --project=$(PROJECT_ID)

deploy: deploy-backend deploy-frontend

# Cloud Build でビルド＆デプロイ（推奨: CI/CD トリガーではなく手動実行する場合）
deploy-cloudbuild:
	gcloud builds submit \
	  --config=cloudbuild.yaml \
	  --substitutions=_REGION=$(REGION),SHORT_SHA=manual-$(shell date +%Y%m%d%H%M) \
	  --project=$(PROJECT_ID) \
	  .

# ---- シークレット管理 ----------------------------------------------------

secrets-list:
	gcloud secrets list --project=$(PROJECT_ID)

secret-set:
	@if [ -z "$(NAME)" ] || [ -z "$(VALUE)" ]; then \
	  echo "使い方: make secret-set NAME=xxx VALUE=yyy"; exit 1; fi
	echo -n "$(VALUE)" | gcloud secrets versions add $(NAME) --data-file=- --project=$(PROJECT_ID)

set-claude-credentials:
	gcloud secrets versions add claude-credentials \
	  --data-file=$$HOME/.claude/credentials.json \
	  --project=$(PROJECT_ID)

# ---- ログ確認 ------------------------------------------------------------

logs-backend:
	gcloud run services logs read kanie-lab-backend \
	  --region=$(REGION) --limit=100 --project=$(PROJECT_ID)

logs-frontend:
	gcloud run services logs read kanie-lab-frontend \
	  --region=$(REGION) --limit=100 --project=$(PROJECT_ID)

# ---- サービス情報 --------------------------------------------------------

status:
	@echo "=== バックエンド ==="
	@gcloud run services describe kanie-lab-backend \
	  --region=$(REGION) --format='value(status.url)' --project=$(PROJECT_ID) 2>/dev/null || echo "未デプロイ"
	@echo ""
	@echo "=== フロントエンド ==="
	@gcloud run services describe kanie-lab-frontend \
	  --region=$(REGION) --format='value(status.url)' --project=$(PROJECT_ID) 2>/dev/null || echo "未デプロイ"

# ---- ヘルプ --------------------------------------------------------------

help:
	@echo "使い方:"
	@echo "  make dev                   - ローカル開発環境を起動"
	@echo "  make setup-gcp             - GCP 初期セットアップ（API キー入力→リソース作成→トリガー設定）"
	@echo "  make first-deploy          - 初回ビルド＆デプロイ（frontend-url 自動設定含む）"
	@echo "  make destroy               - GCP 環境をすべて削除 ⚠️"
	@echo "  make deploy                - バックエンド＆フロントエンドをデプロイ"
	@echo "  make deploy-backend        - バックエンドのみデプロイ"
	@echo "  make deploy-frontend       - フロントエンドのみデプロイ"
	@echo "  make deploy-cloudbuild     - Cloud Build で手動デプロイ"
	@echo "  make logs-backend          - バックエンドのログを確認"
	@echo "  make logs-frontend         - フロントエンドのログを確認"
	@echo "  make status                - デプロイ済みサービスの URL を確認"
	@echo "  make set-claude-credentials - Claude OAuth 認証情報を Secret Manager に登録"
	@echo "  make secret-set NAME=xxx VALUE=yyy - シークレットを設定"
	@echo ""
	@echo "環境変数:"
	@echo "  PROJECT_ID  - GCP プロジェクト ID (現在: $(PROJECT_ID))"
	@echo "  REGION      - リージョン (現在: $(REGION))"
