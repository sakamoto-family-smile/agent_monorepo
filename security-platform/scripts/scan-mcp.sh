#!/bin/bash
# Scan MCP configurations using Snyk Agent Scan.
#
# Iterates over every MCP config declared in config/scan.yaml (targets.mcp_configs)
# so adding a new agent's .mcp.json only requires editing the YAML, not this script.
#
# Requires: uvx, yq (or python3+PyYAML fallback). SNYK_TOKEN environment variable
# for authenticated scans.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# security-platform/scripts/ → security-platform/ → monorepo root
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SCAN_CONFIG="$SCRIPT_DIR/../config/scan.yaml"
RESULTS_DIR="$SCRIPT_DIR/../logs"

echo "=== MCP Security Scan ==="
echo "Repo root: $REPO_ROOT"
echo "Scan config: $SCAN_CONFIG"
echo "Results: $RESULTS_DIR"

mkdir -p "$RESULTS_DIR"

# Extract mcp_configs list from scan.yaml. Prefer yq; fall back to Python.
read_targets() {
    if command -v yq >/dev/null 2>&1; then
        yq -r '.targets.mcp_configs[]' "$SCAN_CONFIG"
    else
        python3 - "$SCAN_CONFIG" <<'PY'
import sys, yaml
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
for p in (data.get("targets") or {}).get("mcp_configs") or []:
    print(p)
PY
    fi
}

i=0
read_targets | while read -r rel_path; do
    [ -z "$rel_path" ] && continue
    i=$((i + 1))
    abs_path="$REPO_ROOT/$rel_path"
    safe_slug="$(echo "$rel_path" | tr '/.' '--')"
    out="$RESULTS_DIR/mcp-scan-${safe_slug}.json"

    if [ ! -f "$abs_path" ]; then
        echo "[$i] SKIP (missing): $rel_path"
        continue
    fi

    echo "[$i] Scanning: $rel_path"
    uvx snyk-agent-scan@latest "$abs_path" --json > "$out" 2>&1 || true
    echo "   -> $out"
done

echo "=== Scan Complete ==="
