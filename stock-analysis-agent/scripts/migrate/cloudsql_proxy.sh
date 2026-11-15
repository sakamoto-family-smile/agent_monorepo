#!/bin/bash
# shared Cloud SQL の stock_analysis_db に手元から繋ぐ (PROPOSAL-0013 のデータ移行用)。
#
#   scripts/migrate/cloudsql_proxy.sh start          # cloud-sql-proxy を 127.0.0.1:15432 で起動
#   eval "$(scripts/migrate/cloudsql_proxy.sh env)"  # CLOUDSQL_DATABASE_URL を export (画面には出さない)
#   scripts/migrate/cloudsql_proxy.sh stop
#
# 前提: brew install cloud-sql-proxy / gcloud auth login / gcloud auth application-default login
# DB パスワードは Secret Manager (terraform が投入した値) から取り出す。
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-sakamomo-family-agent}"
CONNECTION_NAME="${CLOUDSQL_CONNECTION_NAME:-sakamomo-family-agent:asia-northeast1:shared-pg}"
SERVICE_NAME="${SERVICE_NAME:-stock-analysis-line}"
DB_USER="${DB_USER:-stock_analysis_user}"
DB_NAME="${DB_NAME:-stock_analysis_db}"
PROXY_PORT="${CLOUDSQL_PROXY_PORT:-15432}"
RUN_DIR="${TMPDIR:-/tmp}/stock-analysis-cloudsql-proxy"
PID_FILE="$RUN_DIR/proxy.pid"

case "${1:-}" in
  start)
    command -v cloud-sql-proxy >/dev/null || { echo "cloud-sql-proxy が見つかりません (brew install cloud-sql-proxy)" >&2; exit 1; }
    mkdir -p "$RUN_DIR"
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "起動済みです (pid $(cat "$PID_FILE"))"; exit 0
    fi
    cloud-sql-proxy --address 127.0.0.1 --port "$PROXY_PORT" "$CONNECTION_NAME" >"$RUN_DIR/proxy.log" 2>&1 &
    echo $! >"$PID_FILE"
    for _ in $(seq 1 30); do
      grep -q "ready for new connections" "$RUN_DIR/proxy.log" 2>/dev/null && { echo "127.0.0.1:$PROXY_PORT で待ち受けています"; exit 0; }
      kill -0 "$(cat "$PID_FILE")" 2>/dev/null || break
      sleep 1
    done
    echo "cloud-sql-proxy の起動に失敗しました: $RUN_DIR/proxy.log" >&2; exit 1
    ;;
  env)
    password="$(gcloud secrets versions access latest --project "$PROJECT_ID" --secret "$SERVICE_NAME-db-password")"
    encoded="$(printf '%s' "$password" | python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read(), safe=""))')"
    printf 'export CLOUDSQL_DATABASE_URL=%q\n' "postgresql+asyncpg://$DB_USER:$encoded@127.0.0.1:$PROXY_PORT/$DB_NAME"
    ;;
  stop)
    if [ -f "$PID_FILE" ]; then
      kill "$(cat "$PID_FILE")" 2>/dev/null || true
      rm -f "$PID_FILE"
    fi
    echo "停止しました"
    ;;
  *)
    echo "usage: $0 {start|env|stop}" >&2; exit 2
    ;;
esac
