#!/bin/bash
# cutover スクリプト (to_local.sh / to_gcp.sh) の共通部分 (PROPOSAL-0013 §4.4)。
#
# DRY_RUN=1 で実行するコマンドを表示するだけにする (確認・待機も省く)。ASSUME_YES=1 で確認を省く。
# 秘密情報 (DB の URL・トークン) は環境変数で渡し、表示するコマンドには含めない。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
DATA_DIR="${STOCK_LOCAL_DATA_DIR:-$PROJECT_DIR/data/local}"
ENV_FILE="${LOCAL_ENV_FILE:-$PROJECT_DIR/config/local.env}"

PROJECT_ID="${PROJECT_ID:-sakamomo-family-agent}"
REGION="${REGION:-asia-northeast1}"
SERVICE_NAME="${SERVICE_NAME:-stock-analysis-line}"
WORKER_NAME="${WORKER_NAME:-stock-analysis-worker}"
EDINET_JOB_NAME="${EDINET_JOB_NAME:-stock-edinet-index}"
TASKS_QUEUE="${TASKS_QUEUE:-stock-analysis}"
LOCAL_DB_URL="sqlite+aiosqlite:///$DATA_DIR/stock_analysis.db"
QUEUE_DRAIN_TIMEOUT_SECONDS="${QUEUE_DRAIN_TIMEOUT_SECONDS:-900}"

COMPOSE=(docker compose -f "$PROJECT_DIR/docker-compose.local.yml")

is_dry_run() { [ "${DRY_RUN:-0}" = "1" ]; }

step() {
  echo
  echo "== [$1] $2"
}

run() {
  if is_dry_run; then
    printf '+ %s\n' "$*"
  else
    "$@"
  fi
}

confirm() {
  if is_dry_run || [ "${ASSUME_YES:-0}" = "1" ]; then
    echo "(確認を省略) $1"
    return 0
  fi
  local answer
  read -r -p "$1 [y/N] " answer
  [ "$answer" = "y" ] || { echo "中止しました"; exit 1; }
}

die() {
  echo "中止: $*" >&2
  exit 1
}

# config/local.env から値を読む (表示しない)
env_value() {
  grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2-
}

require_env_file() {
  [ -f "$ENV_FILE" ] || die "$ENV_FILE がありません (config/local.env.example から作ってください)"
  local key
  for key in "$@"; do
    [ -n "$(env_value "$key")" ] || die "$ENV_FILE の $key が空です"
  done
}

require_commands() {
  is_dry_run && return 0
  local cmd
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null || die "$cmd が見つかりません"
  done
}

# URL が期待した HTTP ステータスを返すまで待つ
wait_http() {
  local url="$1" expected="$2" timeout="${3:-180}" code=""
  if is_dry_run; then
    echo "+ wait $url → HTTP $expected"
    return 0
  fi
  local deadline=$((SECONDS + timeout))
  while [ $SECONDS -lt $deadline ]; do
    code="$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$url" || true)"
    [ "$code" = "$expected" ] && { echo "OK: $url → HTTP $code"; return 0; }
    sleep 3
  done
  die "$url が HTTP $expected になりません (最後の応答: ${code:-なし})"
}

# app/ をカレントにして運用ツール (app/ops) を動かす
ops() {
  (cd "$PROJECT_DIR/app" && run uv run python -m "ops.$1" "${@:2}")
}

# Cloud SQL に繋ぎ、CLOUDSQL_DATABASE_URL を export する (URL は表示しない)
start_cloudsql_proxy() {
  if is_dry_run; then
    echo "+ scripts/migrate/cloudsql_proxy.sh start / env"
    export CLOUDSQL_DATABASE_URL="postgresql+asyncpg://dry-run"
    return 0
  fi
  "$PROJECT_DIR/scripts/migrate/cloudsql_proxy.sh" start
  eval "$("$PROJECT_DIR/scripts/migrate/cloudsql_proxy.sh" env)"
  trap '"$PROJECT_DIR/scripts/migrate/cloudsql_proxy.sh" stop >/dev/null' EXIT
}

copy_db() {
  local src="$1" dst="$2"
  SRC_DATABASE_URL="$src" DST_DATABASE_URL="$dst" ops db_copy --force
}

gcloud_run() {
  run gcloud --project "$PROJECT_ID" "$@"
}

# Cloud Tasks に残っているタスクが無くなるまで待つ
wait_queue_drained() {
  if is_dry_run; then
    echo "+ wait queue $TASKS_QUEUE が空になるまで"
    return 0
  fi
  local deadline=$((SECONDS + QUEUE_DRAIN_TIMEOUT_SECONDS)) n
  while [ $SECONDS -lt $deadline ]; do
    n="$(gcloud --project "$PROJECT_ID" tasks list --queue "$TASKS_QUEUE" --location "$REGION" --format='value(name)' | wc -l | tr -d ' ')"
    [ "$n" = "0" ] && { echo "OK: queue は空です"; return 0; }
    echo "queue に $n 件残っています。待っています…"
    sleep 10
  done
  die "queue $TASKS_QUEUE が空になりません"
}

remind_redelivery() {
  echo "LINE Developers Console → Messaging API 設定 → Webhook の再送 を $1 にしてください"
  echo "(切替中に届いたメッセージを、切替後に再送させるため。API では変更できません)"
}
