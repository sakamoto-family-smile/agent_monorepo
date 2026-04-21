{#- プロンプトキャッシュヒット率 (設計書 §12.2 重要 KPI)。 -#}

WITH agg AS (
  SELECT
    DATE(event_timestamp) AS dt,
    llm_model,
    SUM(input_tokens)        AS input_tokens_total,
    SUM(cache_read_tokens)   AS cache_read_total,
    SUM(cache_creation_tokens) AS cache_creation_total
  FROM {{ ref('stg_llm_calls') }}
  GROUP BY 1, 2
)
SELECT
  dt,
  llm_model,
  input_tokens_total,
  cache_read_total,
  cache_creation_total,
  CASE
    WHEN input_tokens_total = 0 THEN 0.0
    ELSE CAST(cache_read_total AS DOUBLE) / input_tokens_total
  END AS cache_hit_ratio
FROM agg
