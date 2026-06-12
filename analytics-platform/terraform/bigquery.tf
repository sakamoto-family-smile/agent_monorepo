################################################################################
# Step 4: BigQuery datasets + external table
#
# データセット 3 種:
#   - {bq_raw_dataset}      raw 層 (external table over GCS Hive)
#   - {bq_staging_dataset}  dbt staging
#   - {bq_marts_dataset}    dbt marts
#
# external table は raw bucket の `${gcs_raw_prefix}/` 配下を Hive partitioning
# (mode=AUTO) で参照する。
################################################################################

resource "google_bigquery_dataset" "raw" {
  project       = var.project_id
  dataset_id    = var.bq_raw_dataset
  location      = var.bq_location
  friendly_name = "analytics-platform raw"
  description   = "Raw JSONL events read via external table over GCS Hive partitioning."

  labels = {
    component = "analytics-platform"
    layer     = "raw"
  }
}

resource "google_bigquery_dataset" "staging" {
  project       = var.project_id
  dataset_id    = var.bq_staging_dataset
  location      = var.bq_location
  friendly_name = "analytics-platform staging"
  description   = "dbt staging views (cross-DB compatible SQL)."

  labels = {
    component = "analytics-platform"
    layer     = "staging"
  }
}

resource "google_bigquery_dataset" "marts" {
  project       = var.project_id
  dataset_id    = var.bq_marts_dataset
  location      = var.bq_location
  friendly_name = "analytics-platform marts"
  description   = "dbt marts (KPIs / cache efficiency / delivery health)."

  labels = {
    component = "analytics-platform"
    layer     = "marts"
  }
}

resource "google_bigquery_table" "agent_events_external" {
  count = var.create_bq_external_table ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.raw.dataset_id
  table_id   = var.bq_external_table_name

  # external table は表自体を delete しても GCS データは無傷
  deletion_protection = false

  # PROPOSAL-0010 案E-1: Pub/Sub Cloud Storage サブスクの出力 (NDJSON) を読む。
  # 同出力は Hive partition 形式ではないため hive_partitioning は使わず、
  # service_name / event_type / dt / hour 等はメッセージ JSON 内のカラムとして読む
  # (重複は at-least-once のため dbt staging で event_id dedup する: Phase 5 P5-5)。
  description = "External table over gs://${local.raw_bucket_name}/${var.gcs_events_prefix}/ (Pub/Sub Cloud Storage サブスク出力, NDJSON)."

  external_data_configuration {
    # autodetect は作成時に一部ファイルしかサンプリングせず、event_type ごとの
    # 固有カラム (attributes / input_tokens 等) が欠けることが実運用で判明した
    # (ignore_unknown_values=true のため欠けたカラムは silent に drop される)。
    # schemas.py (AnyEvent union) と揃えた明示スキーマを使う。
    autodetect            = false
    source_format         = "NEWLINE_DELIMITED_JSON"
    ignore_unknown_values = true

    source_uris = [
      "gs://${google_storage_bucket.raw.name}/${var.gcs_events_prefix}/*",
    ]

    # analytics_platform/observability/schemas.py の 7 event_type の union。
    # 共通ベース + 各イベント固有フィールド。attributes (business_event の自由
    # dict) は JSON 型で受ける。
    schema = jsonencode([
      # ── 共通ベース (_BaseEvent) ──
      { name = "event_id", type = "STRING" },
      { name = "event_version", type = "STRING" },
      { name = "event_timestamp", type = "TIMESTAMP" },
      { name = "service_name", type = "STRING" },
      { name = "service_version", type = "STRING" },
      { name = "environment", type = "STRING" },
      { name = "trace_id", type = "STRING" },
      { name = "span_id", type = "STRING" },
      { name = "user_id", type = "STRING" },
      { name = "session_id", type = "STRING" },
      { name = "severity", type = "STRING" },
      { name = "event_type", type = "STRING" },
      # ── llm_call ──
      { name = "llm_provider", type = "STRING" },
      { name = "llm_model", type = "STRING" },
      { name = "llm_request_id", type = "STRING" },
      { name = "input_tokens", type = "INT64" },
      { name = "output_tokens", type = "INT64" },
      { name = "cache_read_tokens", type = "INT64" },
      { name = "cache_creation_tokens", type = "INT64" },
      { name = "total_cost_usd", type = "FLOAT64" },
      { name = "latency_ms", type = "INT64" },
      { name = "ttft_ms", type = "INT64" },
      { name = "stop_reason", type = "STRING" },
      { name = "request_payload_uri", type = "STRING" },
      { name = "response_payload_uri", type = "STRING" },
      # ── tool_invocation ──
      { name = "tool_name", type = "STRING" },
      { name = "tool_server", type = "STRING" },
      { name = "tool_version", type = "STRING" },
      { name = "input_args_hash", type = "STRING" },
      { name = "input_args_uri", type = "STRING" },
      { name = "output_uri", type = "STRING" },
      { name = "output_size_bytes", type = "INT64" },
      { name = "duration_ms", type = "INT64" },
      { name = "status", type = "STRING" },
      { name = "retry_count", type = "INT64" },
      # ── message ── (content_text=schema 定義 / content_inline=ContentRouter 実出力)
      { name = "message_id", type = "STRING" },
      { name = "message_role", type = "STRING" },
      { name = "message_index", type = "INT64" },
      { name = "parent_message_id", type = "STRING" },
      { name = "content_text", type = "STRING" },
      { name = "content_inline", type = "STRING" },
      { name = "content_uri", type = "STRING" },
      { name = "content_hash", type = "STRING" },
      { name = "content_size_bytes", type = "INT64" },
      { name = "content_mime_type", type = "STRING" },
      { name = "content_truncated", type = "BOOL" },
      { name = "content_preview", type = "STRING" },
      { name = "content_summary", type = "STRING" },
      { name = "content_token_count", type = "INT64" },
      { name = "content_language", type = "STRING" },
      # ── conversation_event ──
      { name = "conversation_phase", type = "STRING" },
      { name = "agent_id", type = "STRING" },
      { name = "initial_query_hash", type = "STRING" },
      # ── security_event ──
      { name = "guard_name", type = "STRING" },
      { name = "check_type", type = "STRING" },
      { name = "action_taken", type = "STRING" },
      { name = "risk_score", type = "FLOAT64" },
      { name = "matched_rules", type = "STRING", mode = "REPEATED" },
      { name = "input_snippet_hash", type = "STRING" },
      # ── business_event ──
      { name = "business_domain", type = "STRING" },
      { name = "action", type = "STRING" },
      { name = "resource_type", type = "STRING" },
      { name = "resource_id", type = "STRING" },
      { name = "attributes", type = "JSON" },
      # ── error_event (error_type/error_message は llm_call / tool とも共有) ──
      { name = "error_type", type = "STRING" },
      { name = "error_code", type = "STRING" },
      { name = "error_message", type = "STRING" },
      { name = "error_category", type = "STRING" },
      { name = "stack_trace_uri", type = "STRING" },
      { name = "is_retriable", type = "BOOL" },
    ])
  }

  labels = {
    component = "analytics-platform"
    layer     = "raw"
  }
}
