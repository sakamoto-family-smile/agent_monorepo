#!/bin/bash
# Run Promptfoo red team testing
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$SCRIPT_DIR/.."
RESULTS_DIR="$PLATFORM_DIR/logs"

echo "=== Promptfoo Red Team ==="
mkdir -p "$RESULTS_DIR"

cd "$PLATFORM_DIR"

if ! command -v npx &> /dev/null; then
    echo "ERROR: npx not found. Please install Node.js 18+"
    exit 1
fi

npx promptfoo@latest redteam run \
    --config ".promptfoo/redteam.yaml" \
    --output "$RESULTS_DIR/redteam-$(date +%Y%m%d-%H%M%S).json" \
    --format json || true

echo "=== Red Team Complete ==="
echo "Results: $RESULTS_DIR/"
