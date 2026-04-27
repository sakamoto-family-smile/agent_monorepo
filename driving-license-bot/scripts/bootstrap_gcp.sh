#!/usr/bin/env bash
# 初回のみ手動で実行する GCP プロジェクトのブートストラップ。
#
# やること:
#   1. tfstate 用 GCS バケット作成
#   2. terraform/backend.tf を生成
#   3. 必要 API の前段有効化（Terraform 自身を動かすために必要なもの）
#
# Terraform で扱うとき自体に IAM / serviceusage 権限が必要なため、
# Project Owner 相当のアカウントで `gcloud auth login` 済みであること。
#
# 使い方:
#   GOOGLE_CLOUD_PROJECT=sakamoto-family-agent ./scripts/bootstrap_gcp.sh

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?GOOGLE_CLOUD_PROJECT is required}"
REGION="${REGION:-asia-northeast1}"
TFSTATE_BUCKET="${TFSTATE_BUCKET:-${PROJECT}-driving-license-bot-tfstate}"
TFSTATE_PREFIX="${TFSTATE_PREFIX:-terraform/state}"

echo "[bootstrap] project=${PROJECT} region=${REGION}"
echo "[bootstrap] tfstate bucket=${TFSTATE_BUCKET}"

# 1. プロジェクト確認
if ! gcloud projects describe "${PROJECT}" >/dev/null 2>&1; then
    echo "[bootstrap] FAIL: project ${PROJECT} does not exist or no access" >&2
    exit 1
fi
gcloud config set project "${PROJECT}"

# 2. Terraform 自身が必要とする API を前段で有効化
#    （Terraform で google_project_service を回す前に serviceusage が必要）
echo "[bootstrap] enabling base APIs ..."
gcloud services enable \
    serviceusage.googleapis.com \
    cloudresourcemanager.googleapis.com \
    iam.googleapis.com \
    --project="${PROJECT}"

# 3. tfstate バケット
if gcloud storage buckets describe "gs://${TFSTATE_BUCKET}" >/dev/null 2>&1; then
    echo "[bootstrap] tfstate bucket already exists"
else
    echo "[bootstrap] creating tfstate bucket ..."
    gcloud storage buckets create "gs://${TFSTATE_BUCKET}" \
        --project="${PROJECT}" \
        --location="${REGION}" \
        --uniform-bucket-level-access
    gcloud storage buckets update "gs://${TFSTATE_BUCKET}" --versioning
fi

# 4. backend.tf を生成（tfstate を GCS で持つ）
BACKEND_FILE="$(dirname "$0")/../terraform/backend.tf"
cat >"${BACKEND_FILE}" <<EOF
# 自動生成 (scripts/bootstrap_gcp.sh)
# tfstate は GCS で管理 → 履歴・lock の安全性を確保
terraform {
  backend "gcs" {
    bucket = "${TFSTATE_BUCKET}"
    prefix = "${TFSTATE_PREFIX}"
  }
}
EOF
echo "[bootstrap] wrote ${BACKEND_FILE}"

# 5. terraform.tfvars を作っていなければサンプルを示す
TFVARS="$(dirname "$0")/../terraform/terraform.tfvars"
if [[ ! -f "${TFVARS}" ]]; then
    echo "[bootstrap] copy terraform.tfvars.example → terraform.tfvars and edit"
    cp "$(dirname "$0")/../terraform/terraform.tfvars.example" "${TFVARS}"
    echo "[bootstrap] $(realpath "${TFVARS}") を編集してください"
fi

cat <<'NEXT'

[bootstrap] done. 次のステップ:

  cd driving-license-bot
  make tf-init
  make tf-plan
  make tf-apply

  → 基盤（SA / Firestore / Secret 枠 / Artifact Registry）が作られる

  続いて secret に値を投入:
  echo -n "$LINE_CHANNEL_SECRET" | gcloud secrets versions add driving-license-bot-line-channel-secret --data-file=-
  echo -n "$LINE_CHANNEL_ACCESS_TOKEN" | gcloud secrets versions add driving-license-bot-line-channel-access-token --data-file=-

  image を build & push:
  gcloud builds submit --config=driving-license-bot/cloudbuild.yaml \
      --substitutions=_LOCATION=asia-northeast1,_REPO=driving-license-bot .

  そして line_bot_image を tfvars に書いて再 apply:
  # terraform.tfvars に line_bot_image="<full_uri>:latest" を書く
  make tf-apply
NEXT
