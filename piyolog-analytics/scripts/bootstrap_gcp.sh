#!/usr/bin/env bash
# B4 (実機開通) の最初のステップ: GCP project 側の準備を 1 コマンドにまとめる。
#
# 何をするか (idempotent):
#   1. Terraform state 用 GCS bucket (`${PROJECT}-tfstate`) を作成 + versioning ON
#   2. piyolog-analytics で必要な GCP API をまとめて有効化
#
# 必須 env:
#   PIYOLOG_GCP_PROJECT     GCP project id
#
# 任意 env:
#   PIYOLOG_TFSTATE_LOCATION  state bucket の location (default: US)
#
# 注意:
#   - このスクリプトは GCP 側の操作を行う。実行前に `gcloud auth login` 済みであること。
#   - 実行者は project owner 相当の IAM が必要 (API 有効化 + bucket 作成)。

set -euo pipefail

: "${PIYOLOG_GCP_PROJECT:?PIYOLOG_GCP_PROJECT is required}"

LOCATION="${PIYOLOG_TFSTATE_LOCATION:-US}"
STATE_BUCKET="${PIYOLOG_GCP_PROJECT}-tfstate"

echo "[bootstrap] project=${PIYOLOG_GCP_PROJECT}"
echo "[bootstrap] tfstate bucket=gs://${STATE_BUCKET} (location=${LOCATION})"

# --- 1. state bucket (idempotent) ---

if gsutil ls -b -p "${PIYOLOG_GCP_PROJECT}" "gs://${STATE_BUCKET}" >/dev/null 2>&1; then
  echo "[bootstrap] state bucket exists: gs://${STATE_BUCKET}"
else
  echo "[bootstrap] creating state bucket: gs://${STATE_BUCKET}"
  gsutil mb -p "${PIYOLOG_GCP_PROJECT}" -l "${LOCATION}" "gs://${STATE_BUCKET}"
fi

echo "[bootstrap] enabling versioning on state bucket"
gsutil versioning set on "gs://${STATE_BUCKET}"

# --- 2. API enable ---

echo "[bootstrap] enabling required GCP APIs..."
gcloud services enable \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  storage.googleapis.com \
  cloudscheduler.googleapis.com \
  --project="${PIYOLOG_GCP_PROJECT}"

echo
echo "[bootstrap] done. Next steps:"
echo "  1. cd piyolog-analytics/terraform"
echo "  2. cp terraform.tfvars.example terraform.tfvars  # region / name_prefix を編集"
echo "  3. cat >backend.tf <<EOF"
echo "     terraform {"
echo "       backend \"gcs\" {"
echo "         bucket = \"${STATE_BUCKET}\""
echo "         prefix = \"piyolog-analytics\""
echo "       }"
echo "     }"
echo "     EOF"
echo "  4. export TF_VAR_project_id=\"${PIYOLOG_GCP_PROJECT}\""
echo "  5. cd .. && make tf-init && make tf-plan && make tf-apply"
echo "  6. README §0.5.2 の手順に沿って LINE secrets 投入 + image push + Cloud Run deploy"
