#!/bin/bash
# GCP → ローカル (Mac mini) へ切り替える (PROPOSAL-0013 §4.4)。
#
#   make cutover-to-local            # 本番
#   DRY_RUN=1 make cutover-to-local  # 実行するコマンドを表示するだけ
#
# 順序: ローカルの準備確認 → GCP の受付停止と queue の消化 → Cloud SQL → SQLite へコピーと照合
#      → EDINET の同期 → ローカル起動 → Webhook 切替と疎通 → GCP を standby に
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

step 1 "事前確認"
require_commands docker gcloud uv cloud-sql-proxy terraform curl
require_env_file LINE_CHANNEL_SECRET LINE_CHANNEL_ACCESS_TOKEN CLAUDE_CODE_OAUTH_TOKEN PUBLIC_BASE_URL
PUBLIC_BASE_URL="$(env_value PUBLIC_BASE_URL)"
remind_redelivery "有効"
confirm "Webhook の再送を有効にしましたか?"

step 2 "ローカルを起動して、Funnel 経由で届くか確認"
run mkdir -p "$DATA_DIR"
run "${COMPOSE[@]}" --profile public up -d --build
wait_http "http://127.0.0.1:${STOCK_LOCAL_PORT:-8001}/health" 200
wait_http "$PUBLIC_BASE_URL/api/line/webhook" 405
# コピーの間は SQLite に書かせない (tailscale は動かしたまま)
run "${COMPOSE[@]}" stop backend

step 3 "GCP の受付を止め、Cloud Tasks の残りを消化させる"
confirm "GCP の webhook を非公開にします。続けますか?"
gcloud_run run services remove-iam-policy-binding "$SERVICE_NAME" --region "$REGION" \
  --member=allUsers --role=roles/run.invoker
wait_queue_drained
gcloud_run tasks queues pause "$TASKS_QUEUE" --location "$REGION"

step 4 "Cloud SQL → ローカル SQLite へコピーして照合"
start_cloudsql_proxy
copy_db "$CLOUDSQL_DATABASE_URL" "$LOCAL_DB_URL"

step 5 "EDINET の書類 cache と Edinetcode.csv をローカルへ"
run "$PROJECT_DIR/scripts/migrate/edinet_sync.sh" down

step 6 "ローカルの backend を起動"
run "${COMPOSE[@]}" --profile public up -d backend
wait_http "http://127.0.0.1:${STOCK_LOCAL_PORT:-8001}/health" 200
wait_http "$PUBLIC_BASE_URL/api/line/webhook" 405

step 7 "LINE の Webhook URL をローカルへ切り替えて疎通テスト"
ops line_webhook set "$PUBLIC_BASE_URL/api/line/webhook"

step 8 "GCP を standby にする (webhook 非公開・Scheduler 停止)"
(cd "$PROJECT_DIR/terraform" && run terraform apply -var standby=true)

step 9 "完了"
remind_redelivery "元の設定 (無効)"
echo "LINE で「ヘルプ」「マイリスト」を送り、過去のデータが見えることを確認してください"
