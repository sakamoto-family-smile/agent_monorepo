#!/bin/bash
# Setup cron jobs for automated collection and digest
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$SCRIPT_DIR/.."
PYTHON=$(which python3 || which python)

# Detect uv
if command -v uv &> /dev/null; then
    RUNNER="uv run"
else
    RUNNER="$PYTHON -m"
fi

CRON_COLLECTOR="0 * * * * cd $PLATFORM_DIR && $RUNNER python -m src.collector.main >> $PLATFORM_DIR/logs/collector-cron.log 2>&1"
CRON_ANALYZER="15 * * * * cd $PLATFORM_DIR && $RUNNER python -m src.analyzer.main >> $PLATFORM_DIR/logs/analyzer-cron.log 2>&1"
CRON_DIGEST="0 9 * * * cd $PLATFORM_DIR && $RUNNER python -m src.notifier.digest >> $PLATFORM_DIR/logs/digest-cron.log 2>&1"
CRON_SCAN="0 */6 * * * $PLATFORM_DIR/scripts/scan-mcp.sh >> $PLATFORM_DIR/logs/scan-cron.log 2>&1"

echo "=== Security Platform Cron Setup ==="
echo ""
echo "Add the following to your crontab (run: crontab -e):"
echo ""
echo "# Agent Security Platform - Collector (every hour)"
echo "$CRON_COLLECTOR"
echo ""
echo "# Agent Security Platform - Analyzer (15 min past each hour)"
echo "$CRON_ANALYZER"
echo ""
echo "# Agent Security Platform - Daily Digest (9:00 AM)"
echo "$CRON_DIGEST"
echo ""
echo "# Agent Security Platform - MCP Scan (every 6 hours)"
echo "$CRON_SCAN"
echo ""

read -p "Install these cron jobs automatically? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    (crontab -l 2>/dev/null; echo ""; echo "# Agent Security Platform"; echo "$CRON_COLLECTOR"; echo "$CRON_ANALYZER"; echo "$CRON_DIGEST"; echo "$CRON_SCAN") | crontab -
    echo "Cron jobs installed successfully."
else
    echo "Skipped. Please add manually."
fi
