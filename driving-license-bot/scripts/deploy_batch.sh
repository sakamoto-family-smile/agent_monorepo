#!/usr/bin/env bash
# Cloud Run Job + Cloud Workflows + Cloud Scheduler を idempotent にデプロイする。
#
# 必要な env:
#   GOOGLE_CLOUD_PROJECT
#   ANTHROPIC_VERTEX_PROJECT_ID  (省略時 GOOGLE_CLOUD_PROJECT)
#   CLOUDSQL_INSTANCE_CONNECTION_NAME
#   CLOUDSQL_DB / CLOUDSQL_USER
#   CLOUDSQL_PASSWORD_SECRET (Secret Manager の secret 名)
#   LINE_CHANNEL_SECRET_NAME / LINE_CHANNEL_ACCESS_TOKEN_NAME (Secret Manager 名)
#
# 任意 env:
#   GENERATION_BATCH_SIZE (default 20)
#   BATCH_SCHEDULE_CRON   (default "0 17 * * *" = 毎日 02:00 JST)
#   IMAGE_TAG             (default latest)
#
# 使い方:
#   GOOGLE_CLOUD_PROJECT=myproj ./scripts/deploy_batch.sh

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?GOOGLE_CLOUD_PROJECT is required}"
REGION="${REGION:-asia-northeast1}"
REPO="${ARTIFACT_REPO:-driving-license-bot}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/driving-license-bot:${IMAGE_TAG}"

JOB_NAME="${JOB_NAME:-driving-license-bot-batch}"
WORKFLOW_NAME="${WORKFLOW_NAME:-driving-license-bot-generation-pipeline}"
SCHEDULER_NAME="${SCHEDULER_NAME:-driving-license-bot-batch-nightly}"

GENERATION_BATCH_SIZE="${GENERATION_BATCH_SIZE:-20}"
BATCH_SCHEDULE_CRON="${BATCH_SCHEDULE_CRON:-0 17 * * *}"  # 毎日 17:00 UTC = 02:00 JST
SCHEDULER_TIMEZONE="${SCHEDULER_TIMEZONE:-Asia/Tokyo}"

SA_BATCH="sa-batch@${PROJECT}.iam.gserviceaccount.com"
SA_WORKFLOW="sa-workflow@${PROJECT}.iam.gserviceaccount.com"
SA_SCHEDULER="sa-scheduler@${PROJECT}.iam.gserviceaccount.com"

echo "[deploy_batch] project=${PROJECT} region=${REGION}"
echo "[deploy_batch] image=${IMAGE}"
echo "[deploy_batch] job=${JOB_NAME} workflow=${WORKFLOW_NAME} scheduler=${SCHEDULER_NAME}"

# ---------------------------------------------------------------------------
# 1. Cloud Run Job (idempotent: deploy が create / update どちらも兼ねる)
# ---------------------------------------------------------------------------
echo "[deploy_batch] deploying Cloud Run Job ..."
gcloud run jobs deploy "${JOB_NAME}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --command="python" \
  --args="-m,scripts.run_batch,--total,${GENERATION_BATCH_SIZE}" \
  --service-account="${SA_BATCH}" \
  --task-timeout=30m \
  --max-retries=2 \
  --memory=1Gi \
  --cpu=1 \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT},ANTHROPIC_VERTEX_PROJECT_ID=${ANTHROPIC_VERTEX_PROJECT_ID:-${PROJECT}},CLOUD_ML_REGION=${REGION},QUESTION_BANK_BACKEND=pgvector,REPOSITORY_BACKEND=firestore,CLOUDSQL_INSTANCE_CONNECTION_NAME=${CLOUDSQL_INSTANCE_CONNECTION_NAME},CLOUDSQL_DB=${CLOUDSQL_DB:-question_bank},CLOUDSQL_USER=${CLOUDSQL_USER:-app},CLOUDSQL_HOST=127.0.0.1,CLOUDSQL_PORT=5432" \
  --set-secrets="CLOUDSQL_PASSWORD=${CLOUDSQL_PASSWORD_SECRET:-driving-license-bot-cloudsql-password}:latest,LINE_CHANNEL_SECRET=${LINE_CHANNEL_SECRET_NAME:-driving-license-bot-line-channel-secret}:latest,LINE_CHANNEL_ACCESS_TOKEN=${LINE_CHANNEL_ACCESS_TOKEN_NAME:-driving-license-bot-line-channel-access-token}:latest" \
  --add-cloudsql-instances="${CLOUDSQL_INSTANCE_CONNECTION_NAME}"

# ---------------------------------------------------------------------------
# 2. Cloud Workflows
# ---------------------------------------------------------------------------
echo "[deploy_batch] deploying Cloud Workflow ..."
WORKFLOW_FILE="$(dirname "$0")/../workflows/generation_pipeline.yaml"
gcloud workflows deploy "${WORKFLOW_NAME}" \
  --project="${PROJECT}" \
  --location="${REGION}" \
  --source="${WORKFLOW_FILE}" \
  --service-account="${SA_WORKFLOW}"

# ---------------------------------------------------------------------------
# 3. Cloud Scheduler
# ---------------------------------------------------------------------------
echo "[deploy_batch] upserting Cloud Scheduler job ..."
SCHEDULER_URI="https://workflowexecutions.googleapis.com/v1/projects/${PROJECT}/locations/${REGION}/workflows/${WORKFLOW_NAME}/executions"
SCHEDULER_BODY="$(cat <<JSON
{
  "argument": "{\"project\":\"${PROJECT}\",\"location\":\"${REGION}\",\"job_name\":\"${JOB_NAME}\",\"total\":${GENERATION_BATCH_SIZE},\"difficulty\":\"standard\"}"
}
JSON
)"

if gcloud scheduler jobs describe "${SCHEDULER_NAME}" \
    --project="${PROJECT}" --location="${REGION}" >/dev/null 2>&1; then
  echo "[deploy_batch] updating existing scheduler ..."
  gcloud scheduler jobs update http "${SCHEDULER_NAME}" \
    --project="${PROJECT}" \
    --location="${REGION}" \
    --schedule="${BATCH_SCHEDULE_CRON}" \
    --time-zone="${SCHEDULER_TIMEZONE}" \
    --uri="${SCHEDULER_URI}" \
    --http-method=POST \
    --message-body="${SCHEDULER_BODY}" \
    --oauth-service-account-email="${SA_SCHEDULER}"
else
  echo "[deploy_batch] creating new scheduler ..."
  gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
    --project="${PROJECT}" \
    --location="${REGION}" \
    --schedule="${BATCH_SCHEDULE_CRON}" \
    --time-zone="${SCHEDULER_TIMEZONE}" \
    --uri="${SCHEDULER_URI}" \
    --http-method=POST \
    --message-body="${SCHEDULER_BODY}" \
    --oauth-service-account-email="${SA_SCHEDULER}"
fi

echo "[deploy_batch] done. trigger manually with:"
echo "  gcloud workflows execute ${WORKFLOW_NAME} \\"
echo "      --location=${REGION} --project=${PROJECT} \\"
echo '      --data='"'"'{"project":"'"${PROJECT}"'","location":"'"${REGION}"'"}'"'"
