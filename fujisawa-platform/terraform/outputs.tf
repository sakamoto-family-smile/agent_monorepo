# step 3 (Cloud Run Jobs / Cloud Scheduler) と consumer 側で利用する output。

output "etl_service_account_email" {
  description = "ETL Cloud Run Job が使う Service Account email。Workload Identity binding やデバッグで参照。"
  value       = google_service_account.etl.email
}

output "cloudsql_database_name" {
  description = "fujisawa_kb_db の DB 名。psql / Cloud SQL Auth Proxy 接続文字列で使う。"
  value       = google_sql_database.kb.name
}

output "cloudsql_etl_user_name" {
  description = "ETL 用の PostgreSQL ユーザ名 (psql 接続文字列で使う)。"
  value       = google_sql_user.etl.name
}

output "cloudsql_instance_connection_name" {
  description = "既存 Cloud SQL instance の connection name (step 3 の Cloud Run Job 配線で使う)。"
  value       = var.shared_cloudsql_instance_connection_name
}

output "pdf_archive_bucket_name" {
  description = "PdfArchive bucket 名。Cloud Run Job の env (FUJISAWA_ETL_PDF_ARCHIVE_BUCKET) に渡す。"
  value       = google_storage_bucket.pdf_archive.name
}

output "artifact_registry_repo_url" {
  description = "Docker image push 先 URL (`<region>-docker.pkg.dev/<project>/<repo>`)。"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.fujisawa_etl.repository_id}"
}

output "secret_ids" {
  description = "Secret Manager の secret ID 一覧。値投入 (`gcloud secrets versions add`) で使う。"
  value = {
    db_password    = google_secret_manager_secret.db_password.secret_id
    user_agent     = google_secret_manager_secret.user_agent.secret_id
    vertex_project = google_secret_manager_secret.vertex_project.secret_id
  }
}

output "cloud_run_job_names" {
  description = "deploy された Cloud Run Job 名の一覧。`gcloud run jobs execute <name>` で手動実行可能。"
  value = local.deploy_jobs ? {
    for k, job in google_cloud_run_v2_job.etl : k => job.name
  } : {}
}

output "scheduler_job_names" {
  description = "Cloud Scheduler に登録された Job 名の一覧 (wayback_backfill は除く)。"
  value = local.deploy_jobs ? {
    for k, sched in google_cloud_scheduler_job.etl : k => sched.name
  } : {}
}

output "scheduler_service_account_email" {
  description = "Cloud Scheduler が Cloud Run Job を invoke するための SA email。"
  value       = google_service_account.scheduler.email
}
