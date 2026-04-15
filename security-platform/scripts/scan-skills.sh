#!/bin/bash
# Scan skills directories
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
RESULTS_DIR="$SCRIPT_DIR/../logs"

echo "=== Skills Security Scan ==="
mkdir -p "$RESULTS_DIR"

for system in agent-system-1 agent-system-2; do
    SKILLS_DIR="$REPO_ROOT/$system/skills"
    if [ -d "$SKILLS_DIR" ]; then
        echo "Scanning $system skills..."
        uvx snyk-agent-scan@latest --skills "$SKILLS_DIR" \
            --json > "$RESULTS_DIR/skills-scan-$system.json" 2>&1 || true
        echo "  -> Results: $RESULTS_DIR/skills-scan-$system.json"
    fi
done

echo "=== Skills Scan Complete ==="
