#!/usr/bin/env bash
# Firestore + Cloud SQL を GCS にバックアップ。
#
# - teardown-app の直前に自動実行 (scripts/teardown_app.sh から呼ばれる)
# - 任意のタイミングで手動実行: make backup
#
# 出力先:
#   gs://<PROJECT>-driving-license-bot-backups/firestore/<TS>/   (Firestore export)
#   gs://<PROJECT>-driving-license-bot-backups/cloudsql/<TS>/dump.sql  (SQL dump)
#   gs://<PROJECT>-driving-license-bot-backups/LATEST            (TS 文字列)
#
# 必須権限 (operator 側):
#   - roles/datastore.importExportAdmin (Firestore export)
#   - roles/cloudsql.admin or editor    (Cloud SQL export)
#   - roles/storage.objectAdmin on bucket
# Owner 相当があれば全部含まれる。
#
# bucket service agents (Firestore service agent / Cloud SQL service account)
# への書き込み権限は terraform/backup_bucket.tf で付与済。

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?GOOGLE_CLOUD_PROJECT is required}"
NAME_PREFIX="${NAME_PREFIX:-driving-license-bot}"
BUCKET="gs://${PROJECT}-${NAME_PREFIX}-backups"
INSTANCE="${CLOUDSQL_INSTANCE:-${NAME_PREFIX}-pg}"
DATABASE="${CLOUDSQL_DB:-question_bank}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"

echo "[backup_data] project=${PROJECT}"
echo "[backup_data] bucket=${BUCKET}"
echo "[backup_data] timestamp=${TIMESTAMP}"

# bucket 存在確認 (terraform apply 前なら明示エラー)
if ! gcloud storage ls "${BUCKET}" >/dev/null 2>&1; then
    echo "[backup_data] ERROR: bucket ${BUCKET} が存在しません。" >&2
    echo "[backup_data]   make tf-apply で backup bucket を先に作ってください。" >&2
    exit 2
fi

# ---- 1. Firestore export ----
FS_PATH="${BUCKET}/firestore/${TIMESTAMP}"
echo "[backup_data] firestore → ${FS_PATH}"
if ! gcloud firestore export "${FS_PATH}" --project="${PROJECT}" 2>&1 | tail -5; then
    echo "[backup_data] WARN: Firestore export 失敗 (database 不在の可能性)。続行。" >&2
    FS_OK=false
else
    FS_OK=true
fi

# ---- 2. Cloud SQL export (SQL dump) ----
SQL_PATH="${BUCKET}/cloudsql/${TIMESTAMP}/dump.sql"
echo "[backup_data] cloudsql ${INSTANCE}/${DATABASE} → ${SQL_PATH}"
if gcloud sql instances describe "${INSTANCE}" --project="${PROJECT}" >/dev/null 2>&1; then
    if ! gcloud sql export sql "${INSTANCE}" "${SQL_PATH}" \
        --project="${PROJECT}" \
        --database="${DATABASE}" \
        --offload 2>&1 | tail -5; then
        echo "[backup_data] WARN: Cloud SQL export 失敗。続行。" >&2
        SQL_OK=false
    else
        SQL_OK=true
    fi
else
    echo "[backup_data] WARN: Cloud SQL instance ${INSTANCE} が存在しません。skip。" >&2
    SQL_OK=false
fi

# ---- 3. LATEST pointer (どちらかは成功している前提) ----
if [[ "${FS_OK}" == "true" || "${SQL_OK}" == "true" ]]; then
    echo "${TIMESTAMP}" | gcloud storage cp - "${BUCKET}/LATEST"
    echo "[backup_data] LATEST pointer updated → ${TIMESTAMP}"
else
    echo "[backup_data] ERROR: Firestore も Cloud SQL も export 失敗。LATEST 更新せず。" >&2
    exit 3
fi

echo "[backup_data] done. ts=${TIMESTAMP} firestore=${FS_OK} cloudsql=${SQL_OK}"
