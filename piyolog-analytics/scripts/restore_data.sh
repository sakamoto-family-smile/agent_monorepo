#!/usr/bin/env bash
# 最新の backup を Cloud SQL に復元。
#
# - `make tf-apply` で Cloud SQL を作り直した後に `make restore` を呼ぶ想定
# - 初回 apply で backup 不在なら exit 0 で skip (冪等)
# - dump.sql には DDL (CREATE TABLE 等) と DML (INSERT) が含まれる
#
# 必須権限 (operator 側):
#   - roles/cloudsql.admin or editor    (Cloud SQL import)
#   - roles/storage.objectViewer on bucket
# Owner 相当があれば全部含まれる。
#
# 注意: alembic migration を先に走らせていると DDL 衝突する可能性。
#       restore は **fresh DB への流し込み** を推奨 (migration 走らせない)。

set -euo pipefail

PROJECT="${PIYOLOG_GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:?PIYOLOG_GCP_PROJECT or GOOGLE_CLOUD_PROJECT is required}}"
NAME_PREFIX="${PIYOLOG_NAME_PREFIX:-piyolog}"
BUCKET="gs://${PROJECT}-${NAME_PREFIX}-backups"
INSTANCE="${PIYOLOG_CLOUD_SQL_INSTANCE_NAME:-${NAME_PREFIX}}"
DATABASE="${PIYOLOG_DB_NAME:-piyolog}"

echo "[restore_data] project=${PROJECT}"
echo "[restore_data] bucket=${BUCKET}"
echo "[restore_data] instance=${INSTANCE} database=${DATABASE}"

if ! gcloud storage ls "${BUCKET}" >/dev/null 2>&1; then
    echo "[restore_data] bucket ${BUCKET} が無い → skip (初回 apply 想定)。"
    exit 0
fi

# LATEST pointer を読む
if ! gcloud storage ls "${BUCKET}/LATEST" >/dev/null 2>&1; then
    echo "[restore_data] LATEST pointer 不在 → skip (backup 履歴なし)。"
    exit 0
fi

TIMESTAMP="$(gcloud storage cat "${BUCKET}/LATEST" | tr -d '[:space:]')"
if [[ -z "${TIMESTAMP}" ]]; then
    echo "[restore_data] LATEST が空 → skip。" >&2
    exit 0
fi
echo "[restore_data] latest backup = ${TIMESTAMP}"

# ---- Cloud SQL import ----
SQL_PATH="${BUCKET}/cloudsql/${TIMESTAMP}/dump.sql"
if ! gcloud storage ls "${SQL_PATH}" >/dev/null 2>&1; then
    echo "[restore_data] cloudsql backup 不在 (${SQL_PATH}) → skip。"
    exit 0
fi
if ! gcloud sql instances describe "${INSTANCE}" --project="${PROJECT}" >/dev/null 2>&1; then
    echo "[restore_data] Cloud SQL instance 不在 → skip。"
    exit 0
fi

echo "[restore_data] cloudsql ${INSTANCE}/${DATABASE} ← ${SQL_PATH}"
echo "[restore_data] 注意: alembic migration を先に走らせていると DDL 衝突します。"
echo "[restore_data]   migration なしの fresh DB への restore を推奨。"
if ! gcloud sql import sql "${INSTANCE}" "${SQL_PATH}" \
    --project="${PROJECT}" \
    --database="${DATABASE}" \
    --quiet 2>&1 | tail -5; then
    echo "[restore_data] WARN: Cloud SQL import 失敗。" >&2
    echo "[restore_data]   既存テーブル/データ衝突の可能性。" >&2
    exit 5
fi

echo "[restore_data] done. restored from ts=${TIMESTAMP}"
