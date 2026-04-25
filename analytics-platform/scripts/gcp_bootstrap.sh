#!/usr/bin/env bash
# GCP 側リソース (BigQuery dataset / external table) を初期化する idempotent スクリプト。
#
# 前提:
#   - gcloud / bq CLI が認証済み (`gcloud auth login` + `gcloud auth application-default login`)
#   - GCS バケットは別途作成済み (terraform 等)
#
# env (必須):
#   ANALYTICS_BQ_PROJECT          GCP project id
#   ANALYTICS_GCS_BUCKET          raw JSONL 置き場 (`uploaded/...` を expect)
#
# env (任意):
#   ANALYTICS_BQ_LOCATION         BQ location (default: US)
#   ANALYTICS_BQ_RAW_DATASET      raw dataset (default: analytics_raw)
#   ANALYTICS_BQ_STAGING_DATASET  staging dataset (default: analytics_staging)
#   ANALYTICS_BQ_MARTS_DATASET    marts dataset (default: analytics_marts)
#   ANALYTICS_BQ_RAW_TABLE        external table 名 (default: agent_events_external)
#   ANALYTICS_GCS_RAW_PREFIX      raw JSONL の prefix (default: uploaded/)

set -euo pipefail

: "${ANALYTICS_BQ_PROJECT:?ANALYTICS_BQ_PROJECT is required}"
: "${ANALYTICS_GCS_BUCKET:?ANALYTICS_GCS_BUCKET is required}"

LOCATION="${ANALYTICS_BQ_LOCATION:-US}"
RAW_DATASET="${ANALYTICS_BQ_RAW_DATASET:-analytics_raw}"
STAGING_DATASET="${ANALYTICS_BQ_STAGING_DATASET:-analytics_staging}"
MARTS_DATASET="${ANALYTICS_BQ_MARTS_DATASET:-analytics_marts}"
RAW_TABLE="${ANALYTICS_BQ_RAW_TABLE:-agent_events_external}"
RAW_PREFIX="${ANALYTICS_GCS_RAW_PREFIX:-uploaded/}"

# trailing slash 正規化
RAW_PREFIX="${RAW_PREFIX%/}/"

echo "[bootstrap] project=${ANALYTICS_BQ_PROJECT} location=${LOCATION}"
echo "[bootstrap] datasets: ${RAW_DATASET}, ${STAGING_DATASET}, ${MARTS_DATASET}"
echo "[bootstrap] raw table: ${RAW_DATASET}.${RAW_TABLE}"
echo "[bootstrap] gcs source: gs://${ANALYTICS_GCS_BUCKET}/${RAW_PREFIX}"

# --- 1. データセット作成 (idempotent) ---
for ds in "${RAW_DATASET}" "${STAGING_DATASET}" "${MARTS_DATASET}"; do
  if bq --project_id="${ANALYTICS_BQ_PROJECT}" show --location="${LOCATION}" --dataset "${ds}" >/dev/null 2>&1; then
    echo "[bootstrap] dataset exists: ${ds}"
  else
    echo "[bootstrap] creating dataset: ${ds}"
    bq --project_id="${ANALYTICS_BQ_PROJECT}" --location="${LOCATION}" mk \
      --dataset \
      --description="analytics-platform ${ds}" \
      "${ANALYTICS_BQ_PROJECT}:${ds}"
  fi
done

# --- 2. external table 定義ファイル生成 ---
TMP_DEF=$(mktemp -t bq_external_def.XXXXXX.json)
trap 'rm -f "${TMP_DEF}"' EXIT

cat >"${TMP_DEF}" <<JSON
{
  "sourceFormat": "NEWLINE_DELIMITED_JSON",
  "sourceUris": [
    "gs://${ANALYTICS_GCS_BUCKET}/${RAW_PREFIX}*"
  ],
  "hivePartitioningOptions": {
    "mode": "AUTO",
    "sourceUriPrefix": "gs://${ANALYTICS_GCS_BUCKET}/${RAW_PREFIX}"
  },
  "autodetect": true,
  "ignoreUnknownValues": true
}
JSON

# --- 3. external table 作成 / 更新 ---
TABLE_FQN="${ANALYTICS_BQ_PROJECT}:${RAW_DATASET}.${RAW_TABLE}"
if bq --project_id="${ANALYTICS_BQ_PROJECT}" show --location="${LOCATION}" "${TABLE_FQN}" >/dev/null 2>&1; then
  echo "[bootstrap] updating external table: ${TABLE_FQN}"
  bq --project_id="${ANALYTICS_BQ_PROJECT}" --location="${LOCATION}" update \
    --external_table_definition="${TMP_DEF}" \
    "${TABLE_FQN}"
else
  echo "[bootstrap] creating external table: ${TABLE_FQN}"
  bq --project_id="${ANALYTICS_BQ_PROJECT}" --location="${LOCATION}" mk \
    --external_table_definition="${TMP_DEF}" \
    "${TABLE_FQN}"
fi

echo "[bootstrap] done."
