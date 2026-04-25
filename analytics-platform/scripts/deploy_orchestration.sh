#!/usr/bin/env bash
# Cloud Workflows + Cloud Scheduler を idempotent にデプロイするスクリプト。
#
# 前提:
#   - gcloud CLI 認証済 (`gcloud auth login`)
#   - Cloud Run Job (analytics-platform-dbt) が既にデプロイ済 (Step 7 参照)
#   - Service Accounts 作成済:
#       sa-workflow@${PROJECT}.iam.gserviceaccount.com   (Workflow 実行用)
#       sa-scheduler@${PROJECT}.iam.gserviceaccount.com  (Scheduler → Workflow 起動用)
#   - 必要 API 有効化: workflows.googleapis.com / cloudscheduler.googleapis.com / run.googleapis.com
#
# env (必須):
#   ANALYTICS_GCP_PROJECT          GCP project id
#
# env (任意 / 既定値あり):
#   ANALYTICS_WORKFLOW_LOCATION    Workflow + Scheduler の region (default: us-central1)
#   ANALYTICS_WORKFLOW_NAME        (default: analytics-platform-dbt-pipeline)
#   ANALYTICS_SCHEDULER_NAME       (default: analytics-platform-dbt-hourly)
#   ANALYTICS_SCHEDULE_CRON        (default: "0 * * * *"  = hourly)
#   ANALYTICS_SCHEDULE_TIMEZONE    (default: "Etc/UTC")
#   ANALYTICS_DBT_JOB_NAME         (default: analytics-platform-dbt)
#   ANALYTICS_DBT_JOB_LOCATION     (default: us-central1)
#   ANALYTICS_DBT_COMMAND          (default: run-and-test)
#   ANALYTICS_WORKFLOW_SA          (default: sa-workflow@${PROJECT}.iam.gserviceaccount.com)
#   ANALYTICS_SCHEDULER_SA         (default: sa-scheduler@${PROJECT}.iam.gserviceaccount.com)
#   ANALYTICS_SLACK_WEBHOOK_URL    Slack Incoming Webhook (任意)。未設定なら通知なし。

set -euo pipefail

: "${ANALYTICS_GCP_PROJECT:?ANALYTICS_GCP_PROJECT is required}"

LOCATION="${ANALYTICS_WORKFLOW_LOCATION:-us-central1}"
WORKFLOW_NAME="${ANALYTICS_WORKFLOW_NAME:-analytics-platform-dbt-pipeline}"
SCHEDULER_NAME="${ANALYTICS_SCHEDULER_NAME:-analytics-platform-dbt-hourly}"
SCHEDULE_CRON="${ANALYTICS_SCHEDULE_CRON:-0 * * * *}"
SCHEDULE_TZ="${ANALYTICS_SCHEDULE_TIMEZONE:-Etc/UTC}"
DBT_JOB_NAME="${ANALYTICS_DBT_JOB_NAME:-analytics-platform-dbt}"
DBT_JOB_LOCATION="${ANALYTICS_DBT_JOB_LOCATION:-us-central1}"
DBT_COMMAND="${ANALYTICS_DBT_COMMAND:-run-and-test}"
WORKFLOW_SA="${ANALYTICS_WORKFLOW_SA:-sa-workflow@${ANALYTICS_GCP_PROJECT}.iam.gserviceaccount.com}"
SCHEDULER_SA="${ANALYTICS_SCHEDULER_SA:-sa-scheduler@${ANALYTICS_GCP_PROJECT}.iam.gserviceaccount.com}"
SLACK_WEBHOOK_URL="${ANALYTICS_SLACK_WEBHOOK_URL:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKFLOW_SOURCE="${SCRIPT_DIR}/../workflows/dbt_pipeline.yaml"

if [[ ! -f "${WORKFLOW_SOURCE}" ]]; then
  echo "[orchestration] ERROR: workflow source not found: ${WORKFLOW_SOURCE}" >&2
  exit 1
fi

echo "[orchestration] project=${ANALYTICS_GCP_PROJECT}"
echo "[orchestration] location=${LOCATION}"
echo "[orchestration] workflow=${WORKFLOW_NAME}"
echo "[orchestration] scheduler=${SCHEDULER_NAME} (${SCHEDULE_CRON} ${SCHEDULE_TZ})"
echo "[orchestration] cloud run job=${DBT_JOB_NAME} (${DBT_JOB_LOCATION}) cmd=${DBT_COMMAND}"
echo "[orchestration] workflow SA=${WORKFLOW_SA}"
echo "[orchestration] scheduler SA=${SCHEDULER_SA}"

# --- 1. Workflow デプロイ (deploy は create/update 兼用で idempotent) ---
echo "[orchestration] deploying workflow..."
gcloud workflows deploy "${WORKFLOW_NAME}" \
  --project="${ANALYTICS_GCP_PROJECT}" \
  --location="${LOCATION}" \
  --source="${WORKFLOW_SOURCE}" \
  --service-account="${WORKFLOW_SA}" \
  --description="analytics-platform dbt pipeline (Cloud Run Job orchestration)"

# --- 2. Scheduler が Workflows API に POST する body を生成 ---
TMP_BODY=$(mktemp -t scheduler_body.XXXXXX.json)
trap 'rm -f "${TMP_BODY}"' EXIT

# Workflows API は { "argument": "<JSON 文字列>" } を expect する。
# argument 自体が文字列としてエンコードされた JSON である点に注意。
SCHEDULER_BODY_PROJECT="${ANALYTICS_GCP_PROJECT}" \
SCHEDULER_BODY_DBT_LOCATION="${DBT_JOB_LOCATION}" \
SCHEDULER_BODY_DBT_JOB="${DBT_JOB_NAME}" \
SCHEDULER_BODY_DBT_CMD="${DBT_COMMAND}" \
SCHEDULER_BODY_SLACK="${SLACK_WEBHOOK_URL}" \
python3 - >"${TMP_BODY}" <<'PY'
import json, os
arg = json.dumps({
    "project":      os.environ["SCHEDULER_BODY_PROJECT"],
    "location":     os.environ["SCHEDULER_BODY_DBT_LOCATION"],
    "job_name":     os.environ["SCHEDULER_BODY_DBT_JOB"],
    "dbt_command":  os.environ["SCHEDULER_BODY_DBT_CMD"],
    "slack_webhook": os.environ["SCHEDULER_BODY_SLACK"],
})
print(json.dumps({"argument": arg}))
PY

WORKFLOW_EXEC_URI="https://workflowexecutions.googleapis.com/v1/projects/${ANALYTICS_GCP_PROJECT}/locations/${LOCATION}/workflows/${WORKFLOW_NAME}/executions"

# --- 3. Scheduler 作成 / 更新 ---
if gcloud scheduler jobs describe "${SCHEDULER_NAME}" \
     --project="${ANALYTICS_GCP_PROJECT}" \
     --location="${LOCATION}" >/dev/null 2>&1; then
  echo "[orchestration] updating scheduler: ${SCHEDULER_NAME}"
  SCHED_VERB="update"
else
  echo "[orchestration] creating scheduler: ${SCHEDULER_NAME}"
  SCHED_VERB="create"
fi

gcloud scheduler jobs "${SCHED_VERB}" http "${SCHEDULER_NAME}" \
  --project="${ANALYTICS_GCP_PROJECT}" \
  --location="${LOCATION}" \
  --schedule="${SCHEDULE_CRON}" \
  --time-zone="${SCHEDULE_TZ}" \
  --uri="${WORKFLOW_EXEC_URI}" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body-from-file="${TMP_BODY}" \
  --oauth-service-account-email="${SCHEDULER_SA}" \
  --description="Trigger ${WORKFLOW_NAME} on schedule"

echo "[orchestration] done."
echo "[orchestration] trigger manually with:"
echo "  gcloud workflows execute ${WORKFLOW_NAME} \\"
echo "    --project=${ANALYTICS_GCP_PROJECT} --location=${LOCATION} \\"
echo "    --data=\"\$(cat ${TMP_BODY} | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"argument\"])')\""
