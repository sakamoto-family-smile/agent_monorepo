#!/bin/bash
# SQLite を backup から戻す (PROPOSAL-0013)。backend を止めてから実行する。
#
#   make local-down
#   scripts/local/restore.sh                       # data/local/backups の最新から戻す
#   scripts/local/restore.sh path/to/stock_analysis-YYYYMMDD-HHMMSS.db
#   make local-up
#
# 今の DB は stock_analysis.db.before-restore-<日時> として残す (-wal / -shm も一緒に退避)。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_DIR="${STOCK_LOCAL_DATA_DIR:-$PROJECT_DIR/data/local}"
DB="$DATA_DIR/stock_analysis.db"

if docker compose -f "$PROJECT_DIR/docker-compose.local.yml" ps --status running --services 2>/dev/null | grep -qx backend; then
  echo "backend が動いています。make local-down で止めてから実行してください" >&2
  exit 1
fi

src="${1:-}"
if [ -z "$src" ]; then
  src="$(find "$DATA_DIR/backups" -maxdepth 1 -name 'stock_analysis-*.db' 2>/dev/null | sort | tail -1)"
  [ -n "$src" ] || { echo "backup が見つかりません: $DATA_DIR/backups" >&2; exit 1; }
fi
[ -f "$src" ] || { echo "ファイルがありません: $src" >&2; exit 1; }

if command -v sqlite3 >/dev/null; then
  result="$(sqlite3 "file:$src?mode=ro" "PRAGMA integrity_check")"
  [ "$result" = "ok" ] || { echo "backup が壊れています ($result): $src" >&2; exit 1; }
fi

echo "戻す backup: $src"
read -r -p "今の DB を退避して置き換えます。続けますか? [y/N] " answer
[ "$answer" = "y" ] || { echo "中止しました"; exit 1; }

stamp="$(date +%Y%m%d-%H%M%S)"
for suffix in "" -wal -shm; do
  if [ -f "$DB$suffix" ]; then
    mv "$DB$suffix" "$DB.before-restore-$stamp$suffix"
  fi
done
cp "$src" "$DB"
echo "戻しました。make local-up で起動してください (退避: $DB.before-restore-$stamp)"
