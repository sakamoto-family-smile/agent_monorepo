#!/bin/bash
# backend が作った SQLite の backup (data/local/backups) を外部ディスクや iCloud に毎日コピーする (PROPOSAL-0013)。
#
#   OFFSITE_BACKUP_DIR=/Volumes/Backup/stock-analysis scripts/local/offsite_backup_launchd.sh install
#   scripts/local/offsite_backup_launchd.sh run        # 手動で 1 回コピー (OFFSITE_BACKUP_DIR が必要)
#   scripts/local/offsite_backup_launchd.sh uninstall
#   scripts/local/offsite_backup_launchd.sh status
#
# 毎日 04:00 (backend の backup が 03:00) に動く。スリープ中に過ぎた回は復帰したときに 1 回動く。
# DB ファイル自体には触らず、backend が作った backup ファイルだけを rsync する。
# config/local.env に HEALTHCHECK_PING_BASE があれば、成否を stock-offsite_backup に ping する。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LABEL="local.stock-analysis-agent.offsite-backup"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DATA_DIR="${STOCK_LOCAL_DATA_DIR:-$PROJECT_DIR/data/local}"
LOG="$DATA_DIR/logs/offsite-backup.log"
DOMAIN="gui/$(id -u)"
RETENTION_DAYS="${OFFSITE_RETENTION_DAYS:-60}"

ping_healthcheck() {
  local base
  base="$(grep -E '^HEALTHCHECK_PING_BASE=' "$PROJECT_DIR/config/local.env" 2>/dev/null | cut -d= -f2- || true)"
  [ -n "$base" ] || return 0
  # Ping key が URL に入るので、URL は表示しない
  curl -fsS -m 10 -o /dev/null "${base%/}/stock-offsite_backup$1?create=1" || echo "healthcheck ping に失敗しました" >&2
}

run_copy() {
  local dest="${OFFSITE_BACKUP_DIR:?OFFSITE_BACKUP_DIR を指定してください}"
  local src="$DATA_DIR/backups"
  if [ ! -d "$src" ]; then
    echo "$(date '+%F %T') backup がありません: $src" >&2; ping_healthcheck /fail; exit 1
  fi
  if ! mkdir -p "$dest" 2>/dev/null || [ ! -w "$dest" ]; then
    echo "$(date '+%F %T') コピー先に書けません (外部ディスク未接続?): $dest" >&2; ping_healthcheck /fail; exit 1
  fi
  if ! rsync -a --include 'stock_analysis-*.db' --exclude '*' "$src/" "$dest/"; then
    echo "$(date '+%F %T') rsync に失敗しました" >&2; ping_healthcheck /fail; exit 1
  fi
  find "$dest" -maxdepth 1 -name 'stock_analysis-*.db' -mtime +"$RETENTION_DAYS" -delete
  echo "$(date '+%F %T') コピーしました: $(find "$dest" -maxdepth 1 -name 'stock_analysis-*.db' | wc -l | tr -d ' ') 件 → $dest"
  ping_healthcheck ""
}

case "${1:-}" in
  run)
    run_copy
    ;;
  install)
    dest="${OFFSITE_BACKUP_DIR:?OFFSITE_BACKUP_DIR を指定してください}"
    mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
    cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string><string>$SCRIPT_DIR/offsite_backup_launchd.sh</string><string>run</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>OFFSITE_BACKUP_DIR</key><string>$dest</string>
    <key>STOCK_LOCAL_DATA_DIR</key><string>$DATA_DIR</string>
    <key>OFFSITE_RETENTION_DAYS</key><string>$RETENTION_DAYS</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>0</integer></dict>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "登録しました: $PLIST (コピー先: $dest、ログ: $LOG)"
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "削除しました: $PLIST"
    ;;
  status)
    launchctl print "$DOMAIN/$LABEL" | grep -E "state|last exit|Hour|Minute" || echo "未登録"
    ;;
  *)
    echo "usage: $0 run|install|uninstall|status" >&2
    exit 2
    ;;
esac
