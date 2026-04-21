{#-
  データ配信健全性 (設計書 §12.5)。
  - E2E レイテンシ (event_timestamp → ingested_at の差分)
  - 取り込み件数 (日次 × event_type)
-#}

WITH diffs AS (
  SELECT
    DATE(event_timestamp) AS dt,
    event_type,
    EXTRACT(EPOCH FROM (ingested_at - event_timestamp)) AS delivery_lag_seconds
  FROM {{ ref('stg_agent_events') }}
)
SELECT
  dt,
  event_type,
  COUNT(*)                                    AS event_count,
  AVG(delivery_lag_seconds)                   AS avg_delivery_lag_seconds,
  QUANTILE_CONT(delivery_lag_seconds, 0.95)   AS p95_delivery_lag_seconds,
  MAX(delivery_lag_seconds)                   AS max_delivery_lag_seconds
FROM diffs
GROUP BY 1, 2
