#!/bin/bash
# 開発 PC のツール一覧 (make detection-host) を launchd で 1 日 1 回 (8:30) 作る。
#
#   scripts/host-inventory-launchd.sh install     # 登録してすぐ 1 回動かす
#   scripts/host-inventory-launchd.sh uninstall   # 止めて登録を消す
#   scripts/host-inventory-launchd.sh status
#
# スリープ中に過ぎた回は、復帰したときに 1 回動く (launchd の StartCalendarInterval)。ログイン時にも 1 回動く。
# 9:00 の日次まとめの前に作っておく
# 結果は data/sbom/hosts/<host_id>.json。照合は detection コンテナの次の scan で行う。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="local.security-platform.host-inventory"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$PROJECT_DIR/data/logs/host-inventory.log"
DOMAIN="gui/$(id -u)"

case "${1:-}" in
  install)
    UV="$(command -v uv)" || { echo "uv が見つかりません" >&2; exit 1; }
    mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
    cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UV</string><string>run</string><string>--project</string><string>$PROJECT_DIR</string>
    <string>python</string><string>-m</string><string>src.detection</string><string>host</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
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
    echo "登録しました: $PLIST (ログ: $LOG)"
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
    echo "usage: $0 install|uninstall|status" >&2
    exit 2
    ;;
esac
