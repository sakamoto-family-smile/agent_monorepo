WITH base AS (
  SELECT * FROM {{ ref('stg_agent_events') }}
  WHERE event_type = 'tool_invocation'
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
  tool_name,
  tool_server,
  tool_version,
  input_args_hash,
  input_args_uri,
  output_uri,
  CAST(output_size_bytes AS {{ dbt.type_bigint() }}) AS output_size_bytes,
  CAST(duration_ms AS {{ dbt.type_bigint() }}) AS duration_ms,
  status,
  error_type,
  error_message,
  CAST(retry_count AS {{ dbt.type_bigint() }}) AS retry_count
FROM base
