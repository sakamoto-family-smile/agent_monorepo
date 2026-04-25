################################################################################
# Service Accounts + IAM bindings (Step 5/7/8 の前提)
#
# 4 つの SA を作る:
#   sa-uploader   consumer エージェントが GCS に JSONL / payload を書く SA。
#                 Workload Identity 経由でそれぞれの Cloud Run / GKE Pod に紐づく。
#   sa-dbt        Cloud Run Job (analytics-platform-dbt) 実行 SA。BigQuery に dbt run。
#   sa-workflow   Cloud Workflows 実行 SA。Cloud Run Job を起動する。
#   sa-scheduler  Cloud Scheduler が Workflows を起動するための SA。
#
# 設計書 §3.6 に対応する Service Account 構成。
################################################################################

# --- Service Accounts ------------------------------------------------------

resource "google_service_account" "uploader" {
  project      = var.project_id
  account_id   = local.sa_uploader_id
  display_name = "analytics-platform JSONL/Payload uploader"
  description  = "Used by consumer agents to upload JSONL events and large payloads to GCS."
}

resource "google_service_account" "dbt" {
  project      = var.project_id
  account_id   = local.sa_dbt_id
  display_name = "analytics-platform dbt Cloud Run Job"
  description  = "Used by Cloud Run Job to run dbt against BigQuery."
}

resource "google_service_account" "workflow" {
  project      = var.project_id
  account_id   = local.sa_workflow_id
  display_name = "analytics-platform Cloud Workflows"
  description  = "Used by Cloud Workflows to start the dbt Cloud Run Job."
}

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = local.sa_scheduler_id
  display_name = "analytics-platform Cloud Scheduler"
  description  = "Used by Cloud Scheduler to invoke Cloud Workflows on schedule."
}

# --- Bucket-level IAM ------------------------------------------------------

# uploader: raw / payloads に object create + read。dead_letter はエラー時のみ書く。
resource "google_storage_bucket_iam_member" "uploader_raw_admin" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.uploader.email}"
}

resource "google_storage_bucket_iam_member" "uploader_payloads_admin" {
  bucket = google_storage_bucket.payloads.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.uploader.email}"
}

resource "google_storage_bucket_iam_member" "uploader_dead_letter_admin" {
  bucket = google_storage_bucket.dead_letter.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.uploader.email}"
}

# dbt: raw / payloads から read (BQ external table がアクセスするため、dbt SA は直接読まなくても
#      BQ ジョブが SA のクレデンシャルで GCS を読みに行く)。
resource "google_storage_bucket_iam_member" "dbt_raw_reader" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.dbt.email}"
}

resource "google_storage_bucket_iam_member" "dbt_payloads_reader" {
  bucket = google_storage_bucket.payloads.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.dbt.email}"
}

# --- BigQuery dataset-level IAM -------------------------------------------

# dbt: staging / marts への書き、raw への読み
resource "google_bigquery_dataset_iam_member" "dbt_raw_reader" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.raw.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.dbt.email}"
}

resource "google_bigquery_dataset_iam_member" "dbt_staging_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.staging.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.dbt.email}"
}

resource "google_bigquery_dataset_iam_member" "dbt_marts_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.marts.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.dbt.email}"
}

# dbt がジョブ (query / load) を発行できる project-level role
resource "google_project_iam_member" "dbt_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.dbt.email}"
}

# --- Cloud Run Job invoke (Workflow → dbt Job) -----------------------------

# Workflow が Cloud Run Job を起動できるように。Cloud Run Job 単位の binding は
# Cloud Run Job 自体が Terraform 管理ではないため、project-level に置く。
resource "google_project_iam_member" "workflow_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.workflow.email}"
}

resource "google_project_iam_member" "workflow_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.workflow.email}"
}

# --- Scheduler → Workflows -------------------------------------------------

resource "google_project_iam_member" "scheduler_workflows_invoker" {
  project = var.project_id
  role    = "roles/workflows.invoker"
  member  = "serviceAccount:${google_service_account.scheduler.email}"
}

# --- Artifact Registry pull (dbt Job が image を pull するため) ---------------

resource "google_artifact_registry_repository_iam_member" "dbt_ar_reader" {
  project    = var.project_id
  location   = google_artifact_registry_repository.dbt.location
  repository = google_artifact_registry_repository.dbt.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.dbt.email}"
}
