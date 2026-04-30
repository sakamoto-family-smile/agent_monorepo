#!/usr/bin/env bash
# 最新の backup を Firestore + Cloud SQL に復元。
#
# - tf-apply 後に手動実行: make restore
# - 初回 apply で backup 不在なら exit 0 で skip (冪等)
# - Firestore は default database を import で上書き (既存データは merge ではない)
# - Cloud SQL は dump.sql を実行 (DDL は IF NOT EXISTS、DML は INSERT)
#
# 必須権限 (operator 側):
#   - roles/datastore.importExportAdmin (Firestore import)
#   - roles/cloudsql.admin or editor    (Cloud SQL import)
#   - roles/storage.objectViewer on bucket
# Owner 相当があれば全部含まれる。

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?GOOGLE_CLOUD_PROJECT is required}"
NAME_PREFIX="${NAME_PREFIX:-driving-license-bot}"
BUCKET="gs://${PROJECT}-${NAME_PREFIX}-backups"
INSTANCE="${CLOUDSQL_INSTANCE:-${NAME_PREFIX}-pg}"
DATABASE="${CLOUDSQL_DB:-question_bank}"

echo "[restore_data] project=${PROJECT}"
echo "[restore_data] bucket=${BUCKET}"

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

# ---- 1. Firestore import ----
FS_PATH="${BUCKET}/firestore/${TIMESTAMP}"
# Firestore export は metadata file が `<TS>.overall_export_metadata` の形で出る
FS_META=$(gcloud storage ls "${FS_PATH}" 2>/dev/null | grep '\.overall_export_metadata$' || true)
if [[ -n "${FS_META}" ]]; then
    echo "[restore_data] firestore ← ${FS_META}"
    if ! gcloud firestore import "${FS_META}" --project="${PROJECT}" 2>&1 | tail -5; then
        echo "[restore_data] WARN: Firestore import 失敗。続行。" >&2
    fi
else
    echo "[restore_data] firestore backup 不在 (${FS_PATH}) → skip。"
fi

# ---- 2. Cloud SQL import ----
SQL_PATH="${BUCKET}/cloudsql/${TIMESTAMP}/dump.sql"
if gcloud storage ls "${SQL_PATH}" >/dev/null 2>&1; then
    if gcloud sql instances describe "${INSTANCE}" --project="${PROJECT}" >/dev/null 2>&1; then
        echo "[restore_data] cloudsql ${INSTANCE}/${DATABASE} ← ${SQL_PATH}"
        # 注意: DDL conflict を避けるため、cloudsql-init を先に走らせ済みなら
        # 重複エラーが出る。冪等運用のため fresh DB への restore を推奨。
        if ! gcloud sql import sql "${INSTANCE}" "${SQL_PATH}" \
            --project="${PROJECT}" \
            --database="${DATABASE}" \
            --quiet 2>&1 | tail -5; then
            echo "[restore_data] WARN: Cloud SQL import 失敗。" >&2
            echo "[restore_data]   既存テーブル/データ衝突の可能性。先に DB を drop するか" >&2
            echo "[restore_data]   make cloudsql-init をスキップして再 restore してください。" >&2
        fi
    else
        echo "[restore_data] Cloud SQL instance 不在 → skip。"
    fi
else
    echo "[restore_data] cloudsql backup 不在 (${SQL_PATH}) → skip。"
fi

echo "[restore_data] done."
