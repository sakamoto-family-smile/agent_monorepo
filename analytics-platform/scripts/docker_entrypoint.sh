#!/usr/bin/env bash
# Cloud Run Job (and local docker run) entrypoint。
#
# サブコマンド:
#   run-and-test  (default) — dbt run --target gcp + dbt test --target gcp
#   run                     — dbt run --target gcp
#   test                    — dbt test --target gcp
#   parse                   — dbt parse --target gcp (smoke / 接続なし検証用)
#   shell                   — bash (デバッグ用)
#   <else>                  — そのままコマンドとして exec
#
# 必須 env (Cloud Run Job では Workload Identity 経由で ADC 解決):
#   ANALYTICS_BQ_PROJECT
#
# 任意 env (既定値あり):
#   ANALYTICS_BQ_LOCATION (US)
#   ANALYTICS_BQ_DEFAULT_DATASET (analytics_staging)
#   ANALYTICS_BQ_RAW_DATASET (analytics_raw)
#   ANALYTICS_BQ_RAW_TABLE (agent_events_external)
#   DBT_TARGET (gcp)              — `local` を指定すれば DuckDB 経路でも動く

set -euo pipefail

CMD="${1:-run-and-test}"
shift || true

DBT_TARGET="${DBT_TARGET:-gcp}"

# dbt の cwd は project-dir と同じにする
cd "${DBT_PROJECT_DIR:-/app/dbt}"

# BQ 必須 env のチェック (gcp target 時のみ)
if [[ "${DBT_TARGET}" == "gcp" ]] && [[ -z "${ANALYTICS_BQ_PROJECT:-}" ]]; then
  echo "[entrypoint] ERROR: ANALYTICS_BQ_PROJECT is required for target=gcp" >&2
  exit 64
fi

dbt_run()   { dbt run   --profiles-dir "${DBT_PROFILES_DIR}" --project-dir "${DBT_PROJECT_DIR}" --target "${DBT_TARGET}" "$@"; }
dbt_test()  { dbt test  --profiles-dir "${DBT_PROFILES_DIR}" --project-dir "${DBT_PROJECT_DIR}" --target "${DBT_TARGET}" "$@"; }
dbt_parse() { dbt parse --profiles-dir "${DBT_PROFILES_DIR}" --project-dir "${DBT_PROJECT_DIR}" --target "${DBT_TARGET}" "$@"; }

case "${CMD}" in
  run-and-test)
    echo "[entrypoint] dbt run + test (target=${DBT_TARGET})"
    dbt_run "$@"
    dbt_test "$@"
    ;;
  run)
    echo "[entrypoint] dbt run (target=${DBT_TARGET})"
    dbt_run "$@"
    ;;
  test)
    echo "[entrypoint] dbt test (target=${DBT_TARGET})"
    dbt_test "$@"
    ;;
  parse)
    echo "[entrypoint] dbt parse (target=${DBT_TARGET})"
    dbt_parse "$@"
    ;;
  shell)
    exec bash
    ;;
  *)
    # 未知のサブコマンドはそのまま exec
    exec "${CMD}" "$@"
    ;;
esac
