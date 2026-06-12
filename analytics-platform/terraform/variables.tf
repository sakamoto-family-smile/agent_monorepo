variable "project_id" {
  type        = string
  description = "GCP project id."
}

variable "region" {
  type        = string
  description = "Default region for regional resources (Cloud Run, Workflows, etc)."
  default     = "us-central1"
}

variable "bq_location" {
  type        = string
  description = "BigQuery dataset location (multi-region 'US' / 'EU' or single region like 'asia-northeast1')."
  default     = "US"
}

variable "name_prefix" {
  type        = string
  description = "Prefix to scope resource names (bucket / dataset / SA suffix)."
  default     = "analytics"
}

# ---- GCS buckets (Step 3) ----

variable "gcs_bucket_location" {
  type        = string
  description = "GCS bucket location (US / EU / asia-northeast1 等)."
  default     = "US"
}

variable "gcs_force_destroy" {
  type        = bool
  description = "Whether terraform destroy should delete buckets even when objects remain. Keep false in production."
  default     = false
}

variable "lifecycle_nearline_days" {
  type        = number
  description = "Days from creation before transitioning to NEARLINE."
  default     = 30
}

variable "lifecycle_coldline_days" {
  type        = number
  description = "Days from creation before transitioning to COLDLINE."
  default     = 90
}

variable "lifecycle_archive_days" {
  type        = number
  description = "Days from creation before transitioning to ARCHIVE (or 0 to disable)."
  default     = 365
}

variable "lifecycle_dead_letter_delete_days" {
  type        = number
  description = "Days before deleting dead-lettered objects (separate retention from raw)."
  default     = 90
}

# ---- Artifact Registry (Step 1) ----

variable "ar_repo_name" {
  type        = string
  description = "Artifact Registry Docker repo name for the dbt image."
  default     = "analytics-platform"
}

# ---- BigQuery (Step 4) ----

variable "bq_raw_dataset" {
  type        = string
  description = "BigQuery dataset for raw external table."
  default     = "analytics_raw"
}

variable "bq_staging_dataset" {
  type        = string
  description = "BigQuery dataset for dbt staging models."
  default     = "analytics_staging"
}

variable "bq_marts_dataset" {
  type        = string
  description = "BigQuery dataset for dbt marts."
  default     = "analytics_marts"
}

variable "bq_external_table_name" {
  type        = string
  description = "External table name over GCS Hive partitioned JSONL."
  default     = "agent_events_external"
}

variable "create_bq_external_table" {
  type        = bool
  description = "Whether to create the BQ external table. Set false on first apply if no JSONL exists yet."
  default     = true
}

variable "gcs_raw_prefix" {
  type        = string
  description = "GCS prefix (under raw bucket) where JSONL is uploaded by analytics-platform consumers."
  default     = "uploaded"
}

# ---- Cloud Monitoring (Step 9) ----

variable "enable_alerts" {
  type        = bool
  description = "Whether to create Cloud Monitoring alert policies. Set false for sandbox/dev to avoid noise."
  default     = true
}

variable "notification_email" {
  type        = string
  description = "Email address that receives alert pages. Empty string disables the email channel."
  default     = ""
}

variable "workflow_name_for_filter" {
  type        = string
  description = "Cloud Workflows name used in alert filters. Must match the name deployed by scripts/deploy_orchestration.sh."
  default     = "analytics-platform-dbt-pipeline"
}

variable "cloud_run_job_name_for_filter" {
  type        = string
  description = "Cloud Run Job name used in alert filters. Must match the name deployed in Step 7."
  default     = "analytics-platform-dbt"
}

variable "dbt_job_max_duration_seconds" {
  type        = number
  description = "Threshold for the dbt Cloud Run Job duration alert. 0 disables the duration alert."
  default     = 1800 # 30 分
}

# ---- Pub/Sub ingestion (Phase 5 案E-1 / PROPOSAL-0010) ----

variable "enable_pubsub" {
  type        = bool
  description = "Pub/Sub 入口 (topic / GCS サブスク / dead-letter / IAM) を作るか。false で作らない (段階適用用)。"
  default     = true
}

variable "gcs_events_prefix" {
  type        = string
  description = "Cloud Storage サブスクが raw バケット配下に NDJSON を書く prefix。external table はこの prefix を読む。"
  default     = "events"
}

variable "payload_writer_service_account_emails" {
  type        = list(string)
  description = "payloads bucket への書込を許可する consumer SA email 群 (pubsub backend で inline 閾値超 content を直接 GCS に書くエージェント)。配備後に追記する。"
  default     = []
}

variable "publisher_service_account_emails" {
  type        = list(string)
  description = "events topic への publish を許可する consumer SA email 群 (例: sa-piyolog@...)。配備後に追記する。"
  default     = []
}

variable "pubsub_gcs_max_duration" {
  type        = string
  description = "Cloud Storage サブスクのバッチ flush 最大間隔 (この時間で1ファイル化)。"
  default     = "300s"
}

variable "pubsub_gcs_max_bytes" {
  type        = number
  description = "Cloud Storage サブスクのバッチ flush 最大バイト数 (この量で1ファイル化)。"
  default     = 1000000 # 1 MB
}

variable "dead_letter_max_delivery_attempts" {
  type        = number
  description = "Cloud Storage サブスクの配信失敗が連続したら dead-letter topic へ送る試行回数。"
  default     = 5
}

variable "pubsub_topic_retention_duration" {
  type        = string
  description = "events topic のメッセージ保持期間 (サブスク障害時のバッファ)。"
  default     = "86400s" # 1 日
}

variable "pubsub_message_retention_duration" {
  type        = string
  description = "dead-letter pull サブスクのメッセージ保持期間。"
  default     = "604800s" # 7 日
}
