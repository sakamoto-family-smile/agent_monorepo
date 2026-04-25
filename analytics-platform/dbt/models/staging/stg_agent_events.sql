{#-
  Staging: 共通フィールドだけを正規化して ingested_at を付与 (設計書 §6.2 注記)。
  event_type 別に取り回せる後段ビュー (`stg_llm_calls` 等) のベース。

  - event_timestamp: ISO 8601 文字列 → TIMESTAMPTZ (UTC) (cross_db.parse_event_timestamp)
  - SELECT * EXCEPT(...): DuckDB は EXCLUDE / BQ は EXCEPT (cross_db.star_except)
-#}

WITH src AS (
  SELECT * FROM {{ ref('raw_agent_events') }}
)
SELECT
  event_id,
  event_type,
  event_version,
  {{ parse_event_timestamp('event_timestamp') }} AS event_timestamp,
  CURRENT_TIMESTAMP                              AS ingested_at,
  service_name,
  service_version,
  environment,
  trace_id,
  span_id,
  user_id,
  session_id,
  severity,
  -- 後段 staging ビューが拾えるよう、raw のカラム全部を残す
  src.* {{ star_except([
    'event_id', 'event_type', 'event_version', 'event_timestamp',
    'service_name', 'service_version', 'environment',
    'trace_id', 'span_id', 'user_id', 'session_id', 'severity',
  ]) }}
FROM src
