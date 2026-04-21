#!/usr/bin/env bash
# デモ emit → dbt run → dbt test の一気通貫スモークテスト。
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/3] Emitting demo events..."
uv run python scripts/demo_emit.py --count "${DEMO_COUNT:-20}"

echo "[2/3] Running dbt models..."
(cd dbt && uv run dbt run --profiles-dir . --project-dir .)

echo "[3/3] Running dbt tests..."
(cd dbt && uv run dbt test --profiles-dir . --project-dir .)

echo "Done. DuckDB at ./data/analytics.duckdb"
