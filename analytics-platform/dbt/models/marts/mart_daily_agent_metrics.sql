{#-
  agent × 日 × モデル の KPI (設計書 §11.3)。
  - 呼び出し回数
  - 合計トークン (input / output / cache)
  - 合計コスト
  - p50 / p95 レイテンシ (DuckDB: 厳密 / BQ: 近似)
-#}

SELECT
  {{ date_from_timestamp('event_timestamp') }}        AS dt,
  service_name                                         AS agent_id,
  llm_model,
  COUNT(*)                                             AS call_count,
  SUM(input_tokens)                                    AS total_input_tokens,
  SUM(output_tokens)                                   AS total_output_tokens,
  SUM(cache_read_tokens)                               AS total_cache_read_tokens,
  SUM(cache_creation_tokens)                           AS total_cache_creation_tokens,
  SUM(total_cost_usd)                                  AS total_cost_usd,
  {{ quantile_cont('latency_ms', 0.50) }}              AS p50_latency_ms,
  {{ quantile_cont('latency_ms', 0.95) }}              AS p95_latency_ms,
  SUM(CASE WHEN error_type IS NOT NULL THEN 1 ELSE 0 END) AS error_count
FROM {{ ref('stg_llm_calls') }}
GROUP BY 1, 2, 3
