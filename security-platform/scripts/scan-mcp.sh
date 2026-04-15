#!/bin/bash
# Scan MCP configurations using Snyk Agent Scan
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
RESULTS_DIR="$SCRIPT_DIR/../logs"

echo "=== MCP Security Scan ==="
echo "Repo root: $REPO_ROOT"
echo "Results: $RESULTS_DIR"

mkdir -p "$RESULTS_DIR"

# Scan agent-system-1
if [ -f "$REPO_ROOT/agent-system-1/.mcp.json" ]; then
    echo "[1/2] Scanning agent-system-1 MCP config..."
    uvx snyk-agent-scan@latest "$REPO_ROOT/agent-system-1/.mcp.json" \
        --json > "$RESULTS_DIR/mcp-scan-agent-system-1.json" 2>&1 || true
    echo "  -> Results: $RESULTS_DIR/mcp-scan-agent-system-1.json"
fi

# Scan agent-system-2
if [ -f "$REPO_ROOT/agent-system-2/.mcp.json" ]; then
    echo "[2/2] Scanning agent-system-2 MCP config..."
    uvx snyk-agent-scan@latest "$REPO_ROOT/agent-system-2/.mcp.json" \
        --json > "$RESULTS_DIR/mcp-scan-agent-system-2.json" 2>&1 || true
    echo "  -> Results: $RESULTS_DIR/mcp-scan-agent-system-2.json"
fi

echo "=== Scan Complete ==="
