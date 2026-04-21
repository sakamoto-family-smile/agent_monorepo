{#-
  Staging: 共通フィールドだけを正規化して ingested_at を付与 (設計書 §6.2 注記)。
  event_type 別に取り回せる後段ビュー (`stg_llm_calls` 等) のベース。
-#}

WITH src AS (
  SELECT * FROM {{ ref('raw_agent_events') }}
)
SELECT
  event_id,
  event_type,
  event_version,
  -- read_json_auto は TZ 付 ISO 8601 を naive TIMESTAMP として読むため、
  -- AT TIME ZONE 'UTC' で UTC として解釈し直し TIMESTAMPTZ に昇格する。
  (CAST(event_timestamp AS TIMESTAMP) AT TIME ZONE 'UTC') AS event_timestamp,
  CURRENT_TIMESTAMP                            AS ingested_at,
  service_name,
  service_version,
  environment,
  trace_id,
  span_id,
  user_id,
  session_id,
  severity,
  -- 後段 staging ビューが拾えるよう、raw のカラム全部を残す
  src.*
  EXCLUDE (
    event_id, event_type, event_version, event_timestamp, service_name,
    service_version, environment, trace_id, span_id, user_id, session_id, severity
  )
FROM src
