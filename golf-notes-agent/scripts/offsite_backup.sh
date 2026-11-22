#!/bin/bash
# golf-notes のデータを外部 SSD にコピーする (ホストで動かす。PROPOSAL-0016 §3.3)。
#
#   GOLF_OFFSITE_DIR=/Volumes/Backup/golf-notes scripts/offsite_backup.sh            # 1 回コピー
#   GOLF_OFFSITE_DIR=... scripts/offsite_backup.sh install|uninstall|status           # launchd (毎日 4:30)
#
# コピーするのは data/backup/ (backend が 3 時に作る golf.db の .backup)・data/raw/ (原本 JSON)・
# data/media/ (動画・画像の原本) だけ。書き込み中の data/golf.db は開かない・コピーしない。
# 原本は追記のみなので --delete は付けない (外部 SSD 側にだけ残る世代があってよい)。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="${GOLF_DATA_DIR:-$PROJECT_DIR/data}"
LABEL="local.golf-notes.offsite-backup"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$DATA_DIR/logs/offsite-backup.log"
DOMAIN="gui/$(id -u)"
DRY_RUN="${DRY_RUN:-}"

copy() {
  : "${GOLF_OFFSITE_DIR:?GOLF_OFFSITE_DIR (外部 SSD のコピー先) を指定してください}"
  if [ ! -d "$(dirname "$GOLF_OFFSITE_DIR")" ]; then
    echo "$(date '+%F %T') コピー先の親ディレクトリがありません (外部 SSD が外れている?): $GOLF_OFFSITE_DIR" >&2
    exit 1
  fi
  local flags=(-a --human-readable --itemize-changes)
  [ -n "$DRY_RUN" ] && flags+=(--dry-run)
  mkdir -p "$GOLF_OFFSITE_DIR"
  for dir in backup raw media; do
    [ -d "$DATA_DIR/$dir" ] || continue
    rsync "${flags[@]}" "$DATA_DIR/$dir/" "$GOLF_OFFSITE_DIR/$dir/"
  done
  echo "$(date '+%F %T') copied backup/ raw/ media/ to $GOLF_OFFSITE_DIR${DRY_RUN:+ (dry-run)}"
}

case "${1:-copy}" in
  copy)
    copy
    ;;
  install)
    : "${GOLF_OFFSITE_DIR:?GOLF_OFFSITE_DIR を指定してください}"
    mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
    cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$SCRIPT_DIR/offsite_backup.sh</string><string>copy</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>GOLF_OFFSITE_DIR</key><string>$GOLF_OFFSITE_DIR</string>
    <key>GOLF_DATA_DIR</key><string>$DATA_DIR</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>30</integer></dict>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "登録しました: $PLIST (毎日 4:30、ログ: $LOG)"
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
    echo "usage: $0 [copy|install|uninstall|status]" >&2
    exit 2
    ;;
esac
