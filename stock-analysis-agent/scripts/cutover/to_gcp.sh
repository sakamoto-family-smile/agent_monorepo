#!/bin/bash
# ローカル (Mac mini) → GCP へ切り替える (PROPOSAL-0013 §4.4)。
#
#   make cutover-to-gcp            # 本番
#   DRY_RUN=1 make cutover-to-gcp  # 実行するコマンドを表示するだけ
#
# 順序: 最終 backup → ローカル停止 → 今のコードでイメージを build して Cloud Run に反映
#      → Secret の同期 → standby 解除 → SQLite → Cloud SQL へコピーと照合 (連番補正)
#      → EDINET の同期 → Webhook 切替と疎通 → ローカルを止める
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

step 1 "事前確認"
require_commands docker gcloud uv cloud-sql-proxy terraform git
require_env_file LINE_CHANNEL_ACCESS_TOKEN
if ! is_dry_run && [ -n "$(git -C "$REPO_DIR" status --porcelain -- stock-analysis-agent analytics-platform edinet-client)" ]; then
  echo "注意: コミットされていない変更があります。イメージは作業ツリーの内容で build されます"
fi
SHA="$(git -C "$REPO_DIR" rev-parse --short=7 HEAD)"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$SERVICE_NAME/$SERVICE_NAME:$SHA"
remind_redelivery "有効"
confirm "Webhook の再送を有効にしましたか?"

step 2 "ローカルの最終 backup を取り、backend を止める"
run "${COMPOSE[@]}" exec backend python -c \
  "import asyncio; from services.backup import run_backup; print(asyncio.run(run_backup()))"
run "${COMPOSE[@]}" stop backend

step 3 "今のコードでイメージを build して Cloud Run に反映 ($SHA)"
(cd "$REPO_DIR" && gcloud_run builds submit --config=stock-analysis-agent/cloudbuild.yaml \
  --ignore-file=stock-analysis-agent/cloudbuild.gcloudignore --substitutions="_SHA=$SHA" .)
gcloud_run run services update "$WORKER_NAME" --region "$REGION" --image "$IMAGE"
gcloud_run run services update "$SERVICE_NAME" --region "$REGION" --image "$IMAGE"
if is_dry_run || gcloud --project "$PROJECT_ID" run jobs describe "$EDINET_JOB_NAME" --region "$REGION" >/dev/null 2>&1; then
  gcloud_run run jobs update "$EDINET_JOB_NAME" --region "$REGION" --image "$IMAGE"
fi

step 4 "秘密情報を Secret Manager に同期 (値が違うものだけ)"
ops secrets_sync diff
confirm "上の差分を Secret Manager に反映しますか?"
ops secrets_sync push

step 5 "GCP の standby を解除 (webhook 公開・Scheduler 再開) し、queue を再開"
(cd "$PROJECT_DIR/terraform" && run terraform apply -var standby=false)
gcloud_run tasks queues resume "$TASKS_QUEUE" --location "$REGION"

step 6 "ローカル SQLite → Cloud SQL へコピーして照合 (連番も補正)"
start_cloudsql_proxy
copy_db "$LOCAL_DB_URL" "$CLOUDSQL_DATABASE_URL"

step 7 "EDINET の書類 cache と Edinetcode.csv を GCS へ"
run "$PROJECT_DIR/scripts/migrate/edinet_sync.sh" up

step 8 "LINE の Webhook URL を Cloud Run へ切り替えて疎通テスト"
if is_dry_run; then
  SERVICE_URL="https://$SERVICE_NAME.example.run.app"
else
  SERVICE_URL="$(cd "$PROJECT_DIR/terraform" && terraform output -raw service_url)"
fi
ops line_webhook set "$SERVICE_URL/api/line/webhook"

step 9 "ローカルを止める (データは $DATA_DIR に残る)"
run "${COMPOSE[@]}" --profile public down

step 10 "完了"
remind_redelivery "元の設定 (無効)"
echo "ローカルに戻すときは make cutover-to-local"
