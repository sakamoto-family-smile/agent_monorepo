locals {
  # bucket / SA / dataset 名は ${name_prefix} で名前空間を切る。
  # 例: name_prefix=analytics → buckets: analytics-raw, analytics-payloads, ...
  raw_bucket_name         = "${var.name_prefix}-raw"
  payloads_bucket_name    = "${var.name_prefix}-payloads"
  dead_letter_bucket_name = "${var.name_prefix}-dead-letter"

  # IAM Service Accounts (短い ID は 6-30 chars / 小文字 + 数字 + ハイフン)
  sa_uploader_id  = "sa-uploader"
  sa_dbt_id       = "sa-dbt"
  sa_workflow_id  = "sa-workflow"
  sa_scheduler_id = "sa-scheduler"

  sa_uploader_email  = google_service_account.uploader.email
  sa_dbt_email       = google_service_account.dbt.email
  sa_workflow_email  = google_service_account.workflow.email
  sa_scheduler_email = google_service_account.scheduler.email

  # Artifact Registry image URI (consumer 側はこの値を Cloud Run Job にデプロイ時参照)
  ar_image_uri = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.dbt.repository_id}/analytics-platform-dbt"
}
