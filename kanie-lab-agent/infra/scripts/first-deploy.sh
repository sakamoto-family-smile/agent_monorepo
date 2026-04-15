#!/bin/bash
# 初回デプロイスクリプト
# ビルド → バックエンドデプロイ → フロントエンドデプロイ → frontend-url 自動更新 → バックエンド再デプロイ
#
# 使い方:
#   export PROJECT_ID=your-gcp-project-id
#   export REGION=us-central1
#   bash infra/scripts/first-deploy.sh

set -euo pipefail

: "${PROJECT_ID:?環境変数 PROJECT_ID を設定してください}"
: "${REGION:=us-central1}"

REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/kanie-lab"
BACKEND_SA="kanie-lab-backend@${PROJECT_ID}.iam.gserviceaccount.com"
FRONTEND_SA="kanie-lab-frontend@${PROJECT_ID}.iam.gserviceaccount.com"
FIREBASE_ENV_FILE="infra/scripts/.firebase-config"

echo "========================================================"
echo "  🚀 kanie-lab-agent 初回デプロイ"
echo "========================================================"
echo "  Project : ${PROJECT_ID}"
echo "  Region  : ${REGION}"
echo "  Registry: ${REGISTRY}"
echo ""

gcloud config set project "${PROJECT_ID}"

# Docker 認証設定
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# ---- Firebase 設定の読み込み ----
if [ ! -f "${FIREBASE_ENV_FILE}" ]; then
  echo "エラー: ${FIREBASE_ENV_FILE} が見つかりません。先に make setup-gcp を実行してください。"
  exit 1
fi
# shellcheck disable=SC1090
source "${FIREBASE_ENV_FILE}"

SHORT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "manual")

# ========================================================================
# [1] バックエンドイメージのビルド & プッシュ
# ========================================================================
echo "[1/5] バックエンドイメージをビルド中..."
docker build \
  --file=infra/docker/Dockerfile.backend.prod \
  --tag="${REGISTRY}/backend:${SHORT_SHA}" \
  --tag="${REGISTRY}/backend:latest" \
  --cache-from="${REGISTRY}/backend:latest" \
  . 2>&1 | tail -5
docker push "${REGISTRY}/backend:${SHORT_SHA}" --quiet
docker push "${REGISTRY}/backend:latest" --quiet
echo "  ✓ 完了"

# ========================================================================
# [2] フロントエンドイメージのビルド & プッシュ
# ========================================================================
echo "[2/5] フロントエンドイメージをビルド中..."
docker build \
  --file=infra/docker/Dockerfile.frontend.prod \
  --tag="${REGISTRY}/frontend:${SHORT_SHA}" \
  --tag="${REGISTRY}/frontend:latest" \
  --cache-from="${REGISTRY}/frontend:latest" \
  --build-arg="NEXT_PUBLIC_FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID}" \
  --build-arg="NEXT_PUBLIC_FIREBASE_API_KEY=${FIREBASE_API_KEY}" \
  --build-arg="NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=${FIREBASE_AUTH_DOMAIN}" \
  --build-arg="NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=${FIREBASE_STORAGE_BUCKET}" \
  --build-arg="NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=${FIREBASE_MESSAGING_SENDER_ID}" \
  --build-arg="NEXT_PUBLIC_FIREBASE_APP_ID=${FIREBASE_APP_ID}" \
  . 2>&1 | tail -5
docker push "${REGISTRY}/frontend:${SHORT_SHA}" --quiet
docker push "${REGISTRY}/frontend:latest" --quiet
echo "  ✓ 完了"

# ========================================================================
# [3] バックエンドを Cloud Run にデプロイ
# ========================================================================
echo "[3/5] バックエンドをデプロイ中..."
gcloud run deploy kanie-lab-backend \
  --image="${REGISTRY}/backend:${SHORT_SHA}" \
  --region="${REGION}" \
  --platform=managed \
  --service-account="${BACKEND_SA}" \
  --timeout=3600 \
  --concurrency=1 \
  --max-instances=5 \
  --min-instances=0 \
  --memory=2Gi \
  --cpu=2 \
  --execution-environment=gen2 \
  --no-allow-unauthenticated \
  --set-env-vars="APP_ENV=production,FIREBASE_PROJECT_ID=${PROJECT_ID},GOOGLE_CLOUD_PROJECT=${PROJECT_ID},WORKSPACE_BASE=/tmp/workspace/users" \
  --set-secrets="ANTHROPIC_API_KEY=anthropic-api-key:latest,BRAVE_API_KEY=brave-api-key:latest,ESTAT_APP_ID=estat-app-id:latest,SEMANTIC_SCHOLAR_API_KEY=semantic-scholar-api-key:latest,FRONTEND_URL=frontend-url:latest" \
  --set-secrets="/tmp/claude_credentials.json=claude-credentials:latest" \
  --project="${PROJECT_ID}" \
  --quiet
echo "  ✓ 完了"

# ========================================================================
# [4] フロントエンドを Cloud Run にデプロイ
# ========================================================================
echo "[4/5] フロントエンドをデプロイ中..."
gcloud run deploy kanie-lab-frontend \
  --image="${REGISTRY}/frontend:${SHORT_SHA}" \
  --region="${REGION}" \
  --platform=managed \
  --service-account="${FRONTEND_SA}" \
  --timeout=60 \
  --concurrency=80 \
  --max-instances=10 \
  --min-instances=0 \
  --memory=512Mi \
  --cpu=1 \
  --allow-unauthenticated \
  --project="${PROJECT_ID}" \
  --quiet
echo "  ✓ 完了"

# ========================================================================
# [5] frontend-url を Secret Manager に自動登録 → バックエンド再デプロイ
# ========================================================================
echo "[5/5] frontend-url を自動設定してバックエンドを再デプロイ中..."

FRONTEND_URL=$(gcloud run services describe kanie-lab-frontend \
  --region="${REGION}" \
  --format='value(status.url)' \
  --project="${PROJECT_ID}")

echo "  フロントエンド URL: ${FRONTEND_URL}"

# Secret Manager に登録
echo -n "${FRONTEND_URL}" | gcloud secrets versions add frontend-url \
  --data-file=- --project="${PROJECT_ID}" --quiet

# バックエンドの FRONTEND_URL を更新（CORS 用）
gcloud run services update kanie-lab-backend \
  --region="${REGION}" \
  --update-secrets="FRONTEND_URL=frontend-url:latest" \
  --project="${PROJECT_ID}" \
  --quiet
echo "  ✓ 完了"

# ========================================================================
echo ""
echo "========================================================"
echo "  ✅ デプロイ完了"
echo "========================================================"
echo ""
echo "  フロントエンド: ${FRONTEND_URL}"
echo ""
BACKEND_URL=$(gcloud run services describe kanie-lab-backend \
  --region="${REGION}" \
  --format='value(status.url)' \
  --project="${PROJECT_ID}")
echo "  バックエンド:   ${BACKEND_URL}"
echo ""
echo "  以降の更新デプロイ:"
echo "    git push origin main  # Cloud Build が自動でビルド＆デプロイ"
echo ""
