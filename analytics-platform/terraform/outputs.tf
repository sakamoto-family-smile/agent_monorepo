output "raw_bucket" {
  description = "GCS bucket for raw JSONL events (consumer 側 ANALYTICS_GCS_BUCKET)."
  value       = google_storage_bucket.raw.name
}

output "payloads_bucket" {
  description = "GCS bucket for large payloads (>= inline threshold)."
  value       = google_storage_bucket.payloads.name
}

output "dead_letter_bucket" {
  description = "GCS bucket for dead-lettered JSONL."
  value       = google_storage_bucket.dead_letter.name
}

output "bq_raw_dataset" {
  description = "BigQuery raw dataset id."
  value       = google_bigquery_dataset.raw.dataset_id
}

output "bq_staging_dataset" {
  description = "BigQuery staging dataset id (dbt-bigquery profile target.dataset)."
  value       = google_bigquery_dataset.staging.dataset_id
}

output "bq_marts_dataset" {
  description = "BigQuery marts dataset id."
  value       = google_bigquery_dataset.marts.dataset_id
}

output "bq_external_table" {
  description = "Fully qualified external table id (project:dataset.table)."
  value       = var.create_bq_external_table ? "${var.project_id}:${google_bigquery_dataset.raw.dataset_id}.${var.bq_external_table_name}" : null
}

output "artifact_registry_repo" {
  description = "Artifact Registry repository id (Cloud Build cloudbuild.yaml _REPO 引数と一致させる)."
  value       = google_artifact_registry_repository.dbt.repository_id
}

output "dbt_image_uri_template" {
  description = "Image URI template for the dbt Cloud Run Job. Tag is appended at deploy time."
  value       = "${local.ar_image_uri}:<tag>"
}

output "sa_uploader_email" {
  description = "Service account for consumer agents (uploads to GCS)."
  value       = google_service_account.uploader.email
}

output "sa_dbt_email" {
  description = "Service account for the dbt Cloud Run Job."
  value       = google_service_account.dbt.email
}

output "sa_workflow_email" {
  description = "Service account for Cloud Workflows."
  value       = google_service_account.workflow.email
}

output "sa_scheduler_email" {
  description = "Service account for Cloud Scheduler."
  value       = google_service_account.scheduler.email
}

# ---- Monitoring (Step 9) ----

output "alert_policies" {
  description = "Cloud Monitoring alert policy ids (Step 9)."
  value = compact([
    length(google_monitoring_alert_policy.workflow_failed) > 0 ? google_monitoring_alert_policy.workflow_failed[0].id : "",
    length(google_monitoring_alert_policy.dbt_job_failed) > 0 ? google_monitoring_alert_policy.dbt_job_failed[0].id : "",
    length(google_monitoring_alert_policy.dbt_job_slow) > 0 ? google_monitoring_alert_policy.dbt_job_slow[0].id : "",
  ])
}

output "alert_email_channel" {
  description = "Email notification channel id (empty if notification_email was not set)."
  value       = length(google_monitoring_notification_channel.email) > 0 ? google_monitoring_notification_channel.email[0].id : null
}

# 既存の env テンプレート (.env.example) と対応する一括出力。
# `terraform output -json env_for_dotenv | jq -r 'to_entries[]|"\(.key)=\(.value)"'`
output "env_for_dotenv" {
  description = "consumer / dbt / workflow が使う env 変数の正解値一式。.env に流し込む用。"
  value = {
    ANALYTICS_GCP_PROJECT        = var.project_id
    ANALYTICS_GCS_BUCKET         = google_storage_bucket.raw.name
    ANALYTICS_GCS_PAYLOAD_PREFIX = "payloads/"
    ANALYTICS_GCS_RAW_PREFIX     = "${var.gcs_raw_prefix}/"
    ANALYTICS_BQ_PROJECT         = var.project_id
    ANALYTICS_BQ_LOCATION        = var.bq_location
    ANALYTICS_BQ_RAW_DATASET     = google_bigquery_dataset.raw.dataset_id
    ANALYTICS_BQ_STAGING_DATASET = google_bigquery_dataset.staging.dataset_id
    ANALYTICS_BQ_MARTS_DATASET   = google_bigquery_dataset.marts.dataset_id
    ANALYTICS_BQ_DEFAULT_DATASET = google_bigquery_dataset.staging.dataset_id
    ANALYTICS_BQ_RAW_TABLE       = var.bq_external_table_name
    ANALYTICS_DBT_JOB_LOCATION   = var.region
    ANALYTICS_WORKFLOW_LOCATION  = var.region
    ANALYTICS_WORKFLOW_SA        = google_service_account.workflow.email
    ANALYTICS_SCHEDULER_SA       = google_service_account.scheduler.email
  }
}
