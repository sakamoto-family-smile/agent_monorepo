#!/usr/bin/env bash
# Cloud SQL (Postgres) を GCS にバックアップ。
#
# - `make backup` から呼ばれる (`make tf-destroy` 前に手動実行する想定)
# - 対象: piyolog database 内の全テーブル
#   (piyolog_events / import_batches / sessions / conversations / conversation_messages)
#
# 出力先:
#   gs://<PROJECT>-piyolog-backups/cloudsql/<TS>/dump.sql  (SQL dump)
#   gs://<PROJECT>-piyolog-backups/LATEST                  (TS 文字列)
#
# 必須権限 (operator 側):
#   - roles/cloudsql.admin or editor    (Cloud SQL export)
#   - roles/storage.objectAdmin on bucket
# Owner 相当があれば全部含まれる。
#
# bucket service agents (Cloud SQL service account) への書き込み権限は
# terraform/backup_bucket.tf で付与済。

set -euo pipefail

PROJECT="${PIYOLOG_GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:?PIYOLOG_GCP_PROJECT or GOOGLE_CLOUD_PROJECT is required}}"
NAME_PREFIX="${PIYOLOG_NAME_PREFIX:-piyolog}"
BUCKET="gs://${PROJECT}-${NAME_PREFIX}-backups"
INSTANCE="${PIYOLOG_CLOUD_SQL_INSTANCE_NAME:-${NAME_PREFIX}}"
DATABASE="${PIYOLOG_DB_NAME:-piyolog}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"

echo "[backup_data] project=${PROJECT}"
echo "[backup_data] bucket=${BUCKET}"
echo "[backup_data] instance=${INSTANCE} database=${DATABASE}"
echo "[backup_data] timestamp=${TIMESTAMP}"

# bucket 存在確認 (terraform apply 前なら明示エラー)
if ! gcloud storage ls "${BUCKET}" >/dev/null 2>&1; then
    echo "[backup_data] ERROR: bucket ${BUCKET} が存在しません。" >&2
    echo "[backup_data]   make tf-apply で backup bucket を先に作ってください。" >&2
    exit 2
fi

# ---- Cloud SQL export (SQL dump) ----
SQL_PATH="${BUCKET}/cloudsql/${TIMESTAMP}/dump.sql"
echo "[backup_data] cloudsql ${INSTANCE}/${DATABASE} → ${SQL_PATH}"
if ! gcloud sql instances describe "${INSTANCE}" --project="${PROJECT}" >/dev/null 2>&1; then
    echo "[backup_data] ERROR: Cloud SQL instance ${INSTANCE} が存在しません。" >&2
    exit 3
fi

# `--offload` で Cloud SQL 側で実行 (本番への影響を最小化)
if ! gcloud sql export sql "${INSTANCE}" "${SQL_PATH}" \
    --project="${PROJECT}" \
    --database="${DATABASE}" \
    --offload 2>&1 | tail -5; then
    echo "[backup_data] ERROR: Cloud SQL export 失敗。" >&2
    exit 4
fi

# ---- LATEST pointer 更新 ----
echo "${TIMESTAMP}" | gcloud storage cp - "${BUCKET}/LATEST"
echo "[backup_data] LATEST pointer updated → ${TIMESTAMP}"
echo "[backup_data] done. ts=${TIMESTAMP}"
