#!/usr/bin/env bash
# Cloud Run service として piyolog-analytics をデプロイする idempotent スクリプト。
#
# 前提:
#   - Artifact Registry に image が push 済 (`make docker-push` 経由)
#   - Cloud SQL instance + secrets が準備済 (B3 Terraform で作成)
#   - 必要 API: run.googleapis.com / sqladmin.googleapis.com / secretmanager.googleapis.com
#
# 必須 env:
#   PIYOLOG_GCP_PROJECT             GCP project id
#   PIYOLOG_AR_LOCATION             Artifact Registry / Cloud Run region (例: us-central1)
#   PIYOLOG_AR_REPO                 Artifact Registry repo 名 (例: piyolog-analytics)
#   PIYOLOG_IMAGE_TAG               image tag (例: latest, または SHORT_SHA)
#   PIYOLOG_CLOUD_SQL_INSTANCE      Cloud SQL connection name (project:region:instance)
#   PIYOLOG_CLOUD_RUN_SA            実行 SA (例: sa-piyolog@${PROJECT}.iam.gserviceaccount.com)
#   PIYOLOG_FAMILY_USER_IDS         CSV (LINE userId 許可リスト)
#
# 任意 env:
#   PIYOLOG_SERVICE_NAME            (default: piyolog-analytics)
#   PIYOLOG_REGION                  (default: ${PIYOLOG_AR_LOCATION})
#   PIYOLOG_FAMILY_ID               (default: default)
#   PIYOLOG_DEFAULT_CHILD_ID        (default: default)
#   PIYOLOG_LOG_LEVEL               (default: INFO)
#   PIYOLOG_APP_ENV                 (default: prod)
#
# Secret Manager に以下のシークレットが存在する前提:
#   piyolog-line-channel-secret             LINE Messaging API channel secret
#   piyolog-line-channel-access-token       LINE Messaging API access token
#   piyolog-database-url                    SQLAlchemy URL (postgresql+asyncpg://user:pass@/db?host=/cloudsql/...)
#
# 実行: bash scripts/deploy_cloud_run.sh

set -euo pipefail

: "${PIYOLOG_GCP_PROJECT:?PIYOLOG_GCP_PROJECT is required}"
: "${PIYOLOG_AR_LOCATION:?PIYOLOG_AR_LOCATION is required}"
: "${PIYOLOG_AR_REPO:?PIYOLOG_AR_REPO is required}"
: "${PIYOLOG_IMAGE_TAG:?PIYOLOG_IMAGE_TAG is required}"
: "${PIYOLOG_CLOUD_SQL_INSTANCE:?PIYOLOG_CLOUD_SQL_INSTANCE is required}"
: "${PIYOLOG_CLOUD_RUN_SA:?PIYOLOG_CLOUD_RUN_SA is required}"
: "${PIYOLOG_FAMILY_USER_IDS:?PIYOLOG_FAMILY_USER_IDS is required}"

SERVICE_NAME="${PIYOLOG_SERVICE_NAME:-piyolog-analytics}"
REGION="${PIYOLOG_REGION:-${PIYOLOG_AR_LOCATION}}"
FAMILY_ID="${PIYOLOG_FAMILY_ID:-default}"
DEFAULT_CHILD_ID="${PIYOLOG_DEFAULT_CHILD_ID:-default}"
LOG_LEVEL="${PIYOLOG_LOG_LEVEL:-INFO}"
APP_ENV="${PIYOLOG_APP_ENV:-prod}"

IMAGE_URI="${PIYOLOG_AR_LOCATION}-docker.pkg.dev/${PIYOLOG_GCP_PROJECT}/${PIYOLOG_AR_REPO}/piyolog-analytics:${PIYOLOG_IMAGE_TAG}"

echo "[deploy] service=${SERVICE_NAME} region=${REGION}"
echo "[deploy] image=${IMAGE_URI}"
echo "[deploy] sa=${PIYOLOG_CLOUD_RUN_SA}"
echo "[deploy] cloud_sql=${PIYOLOG_CLOUD_SQL_INSTANCE}"

# Cloud Run の env を構築。LINE secret / DATABASE_URL は Secret Manager から mount。
# 残りは plain env で渡す。
SECRETS_FLAGS=(
  "--update-secrets=LINE_CHANNEL_SECRET=piyolog-line-channel-secret:latest"
  "--update-secrets=LINE_CHANNEL_ACCESS_TOKEN=piyolog-line-channel-access-token:latest"
  "--update-secrets=DATABASE_URL=piyolog-database-url:latest"
)

# `,` を含む値は `--set-env-vars` の文法で `^@^` 等で区切り直す必要があるため、
# `--update-env-vars` を 1 行ずつ呼び出す。
ENV_VARS=(
  "APP_ENV=${APP_ENV}"
  "LOG_LEVEL=${LOG_LEVEL}"
  "FAMILY_ID=${FAMILY_ID}"
  "DEFAULT_CHILD_ID=${DEFAULT_CHILD_ID}"
  "DB_AUTO_CREATE=false"
  "ANALYTICS_ENABLED=true"
  "ANALYTICS_SERVICE_NAME=piyolog-analytics"
)

# `FAMILY_USER_IDS` は CSV で `,` を含むため、別途 `--update-env-vars` で
# delimiter 指定で渡す。`^@^` を区切り文字に使うのが gcloud 推奨。
SET_ENV_DELIM="--set-env-vars=^@^FAMILY_USER_IDS=${PIYOLOG_FAMILY_USER_IDS}"

gcloud run deploy "${SERVICE_NAME}" \
  --project="${PIYOLOG_GCP_PROJECT}" \
  --region="${REGION}" \
  --image="${IMAGE_URI}" \
  --platform=managed \
  --service-account="${PIYOLOG_CLOUD_RUN_SA}" \
  --add-cloudsql-instances="${PIYOLOG_CLOUD_SQL_INSTANCE}" \
  --port=8200 \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=2 \
  --concurrency=20 \
  --timeout=120s \
  --allow-unauthenticated \
  --update-env-vars="$(IFS=, ; echo "${ENV_VARS[*]}")" \
  "${SET_ENV_DELIM}" \
  "${SECRETS_FLAGS[@]}"

echo "[deploy] done."
URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --project="${PIYOLOG_GCP_PROJECT}" --region="${REGION}" --format='value(status.url)')
echo "[deploy] service URL: ${URL}"
echo "[deploy] LINE webhook URL: ${URL}/api/line/webhook"
