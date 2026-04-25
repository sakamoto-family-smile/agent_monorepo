WITH base AS (
  SELECT * FROM {{ ref('stg_agent_events') }}
  WHERE event_type = 'message'
)
SELECT
  event_id,
  event_timestamp,
  ingested_at,
  service_name,
  service_version,
  environment,
  trace_id,
  span_id,
  user_id,
  session_id,
  severity,
  message_id,
  message_role,
  CAST(message_index AS {{ dbt.type_bigint() }}) AS message_index,
  parent_message_id,
  content_text,
  content_uri,
  content_hash,
  CAST(content_size_bytes AS {{ dbt.type_bigint() }}) AS content_size_bytes,
  content_mime_type,
  CAST(content_truncated AS {{ dbt.type_boolean() }}) AS content_truncated,
  content_preview,
  content_summary,
  CAST(content_token_count AS {{ dbt.type_bigint() }}) AS content_token_count,
  content_language
FROM base
