#!/usr/bin/env bash
# security-platform/MCP Proxy への到達性とモードをスモークチェックする。
#
# Phase 2-F の暫定運用:
# - 駆動するのはあくまで .mcp.json に列挙された MCP の宣言確認まで
# - 実 MCP サーバ（law-mcp / signs-mcp 等）は Phase 4 で実装予定
# - 現時点では security-platform 側で proxy を `passive` モードで起動していれば
#   このスクリプトが healthy を返す
#
# 使い方:
#   cd driving-license-bot
#   ./scripts/verify_mcp_proxy.sh                 # 既定 http://localhost:8080
#   SECURITY_MCP_PROXY_URL=http://... ./scripts/verify_mcp_proxy.sh

set -euo pipefail

PROXY_URL="${SECURITY_MCP_PROXY_URL:-http://localhost:8080}"

echo "[verify_mcp_proxy] target=${PROXY_URL}"

# 1. 到達性
if ! curl -sS --max-time 5 -o /dev/null -w "%{http_code}\n" "${PROXY_URL}/health" >/tmp/_proxy_status 2>&1; then
    echo "[verify_mcp_proxy] FAIL: cannot reach ${PROXY_URL}/health"
    echo "  → security-platform を起動しているか確認してください:"
    echo "      cd security-platform && uv run uvicorn src.proxy.server:app --port 8080"
    exit 1
fi

STATUS=$(cat /tmp/_proxy_status)
echo "[verify_mcp_proxy] /health status=${STATUS}"
if [[ "${STATUS}" -ge 500 ]]; then
    echo "[verify_mcp_proxy] FAIL: proxy returned 5xx"
    exit 1
fi

# 2. .mcp.json の declarations を表示（運用者の目視確認用）
MCP_FILE="$(dirname "$0")/../.mcp.json"
if [[ -f "${MCP_FILE}" ]]; then
    echo "[verify_mcp_proxy] declared MCPs in $(basename "${MCP_FILE}"):"
    python3 -c "
import json, sys
with open('${MCP_FILE}') as f:
    cfg = json.load(f)
servers = cfg.get('mcpServers', {})
for k, v in servers.items():
    print(f'  - {k}: {v.get(\"transport\", \"?\")} → {v.get(\"url\", v.get(\"command\", \"?\"))}')
"
else
    echo "[verify_mcp_proxy] WARN: ${MCP_FILE} not found"
fi

# 3. security-platform の inventory.yaml で driving-license-bot が登録されているか
INVENTORY_FILE="$(dirname "$0")/../../security-platform/config/inventory.yaml"
if [[ -f "${INVENTORY_FILE}" ]]; then
    if grep -q "driving-license-bot" "${INVENTORY_FILE}"; then
        echo "[verify_mcp_proxy] OK: driving-license-bot is registered in security-platform/config/inventory.yaml"
    else
        echo "[verify_mcp_proxy] WARN: driving-license-bot NOT found in inventory.yaml"
    fi
fi

echo "[verify_mcp_proxy] done. proxy mode is configured in security-platform/config/scan.yaml"
echo "[verify_mcp_proxy]   → 'gateway.mode' で passive / active を切替"
