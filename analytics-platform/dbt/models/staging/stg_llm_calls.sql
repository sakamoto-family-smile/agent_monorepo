WITH base AS (
  SELECT * FROM {{ ref('stg_agent_events') }}
  WHERE event_type = 'llm_call'
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
  llm_provider,
  llm_model,
  llm_request_id,
  CAST(input_tokens  AS BIGINT) AS input_tokens,
  CAST(output_tokens AS BIGINT) AS output_tokens,
  CAST(COALESCE(cache_read_tokens, 0)     AS BIGINT) AS cache_read_tokens,
  CAST(COALESCE(cache_creation_tokens, 0) AS BIGINT) AS cache_creation_tokens,
  CAST(total_cost_usd AS DOUBLE) AS total_cost_usd,
  CAST(latency_ms AS BIGINT) AS latency_ms,
  CAST(ttft_ms    AS BIGINT) AS ttft_ms,
  stop_reason,
  request_payload_uri,
  response_payload_uri,
  error_type,
  error_message
FROM base
