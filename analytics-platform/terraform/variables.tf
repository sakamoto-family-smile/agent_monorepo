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
