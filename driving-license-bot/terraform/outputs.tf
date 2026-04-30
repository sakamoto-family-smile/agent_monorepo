output "project_id" {
  value = var.project_id
}

output "region" {
  value = var.region
}

# Service Account
output "sa_line_bot_email" {
  value = local.sa_line_bot_email
}

# Phase 2-A3: バッチ生成 pipeline 用 SA
output "sa_batch_email" {
  description = "Cloud Run Job が利用する SA（自動生成バッチ）"
  value       = local.sa_batch_email
}

output "sa_workflow_email" {
  description = "Workflows が Cloud Run Job を起動する SA"
  value       = local.sa_workflow_email
}

output "sa_scheduler_email" {
  description = "Scheduler が Workflow を nightly 起動する SA"
  value       = local.sa_scheduler_email
}

# Secret Manager
output "secret_names" {
  value = {
    line_channel_secret       = google_secret_manager_secret.line_channel_secret.secret_id
    line_channel_access_token = google_secret_manager_secret.line_channel_access_token.secret_id
    line_login_channel_secret = google_secret_manager_secret.line_login_channel_secret.secret_id
    operator_user_ids         = google_secret_manager_secret.operator_user_ids.secret_id
    cloudsql_password         = google_secret_manager_secret.cloudsql_password.secret_id
  }
}

# ---- Cloud SQL (Phase 2-A1) ----

output "cloudsql_instance_name" {
  description = "Cloud SQL instance 名（gcloud sql connect 等で使う）"
  value       = google_sql_database_instance.main.name
}

output "cloudsql_instance_connection_name" {
  description = "Cloud SQL Auth Proxy / Cloud Run の add-cloudsql-instances に渡す `<project>:<region>:<instance>` 形式"
  value       = google_sql_database_instance.main.connection_name
}

output "cloudsql_database_name" {
  description = "アプリが接続する Postgres database 名"
  value       = google_sql_database.question_bank.name
}

output "cloudsql_user_name" {
  description = "アプリが接続する Postgres user 名（パスワードは Secret Manager 参照）"
  value       = google_sql_user.app.name
}

# ---- Cloud Run Job + Workflow + Scheduler (Phase 2-B2) ----

output "batch_job_name" {
  description = "Cloud Run Job (生成バッチ) の名前。batch_image を空にした初回 apply では null。"
  value       = local.deploy_batch ? google_cloud_run_v2_job.batch[0].name : null
}

output "workflow_name" {
  description = "Cloud Workflow の名前。手動起動: gcloud workflows execute <name> --location=<region>"
  value       = local.deploy_batch ? google_workflows_workflow.generation_pipeline[0].name : null
}

output "scheduler_job_name" {
  description = "Cloud Scheduler の名前。手動 fire: gcloud scheduler jobs run <name> --location=<region>"
  value       = local.deploy_batch ? google_cloud_scheduler_job.batch_nightly[0].name : null
}

# ---- review-admin-ui (Phase 2-C3) ----

output "review_admin_url" {
  description = "review-admin-ui の URL。/login で Google OAuth → allowlist 内の email でログインできる。"
  value       = local.deploy_admin_ui ? google_cloud_run_v2_service.admin_ui[0].uri : null
}

output "review_admin_oauth_redirect_url" {
  description = "OAuth client の Authorized redirect URIs に登録する値 (Console で手動設定)。"
  value       = local.deploy_admin_ui ? "${google_cloud_run_v2_service.admin_ui[0].uri}/auth/callback" : null
}

output "sa_admin_ui_email" {
  description = "review-admin-ui Cloud Run が利用する SA。"
  value       = local.deploy_admin_ui ? google_service_account.admin_ui.email : null
}

# ---- Backup bucket (Phase 2-Y1) ----

output "backup_bucket_name" {
  description = "Firestore + Cloud SQL のバックアップ先 GCS bucket 名。"
  value       = google_storage_bucket.backups.name
}

output "backup_bucket_uri" {
  description = "バックアップ先 GCS URI (gs://...)。scripts/backup_data.sh が使用。"
  value       = "gs://${google_storage_bucket.backups.name}"
}

# Artifact Registry
output "ar_image_uri_base" {
  description = "Cloud Build / push 時に使う image base. tag を付けて push する: <base>:<sha>"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.main.repository_id}"
}

# Cloud Run Service URL（line_bot_image を指定して deploy した場合のみ）
output "line_bot_service_url" {
  description = "LINE Webhook URL に登録すべき URL（末尾に /webhook を付ける）"
  value       = local.deploy_line_bot ? google_cloud_run_v2_service.line_bot[0].uri : null
}

output "line_bot_webhook_url" {
  description = "LINE Developers Console の Webhook URL に貼る完全 URL"
  value       = local.deploy_line_bot ? "${google_cloud_run_v2_service.line_bot[0].uri}/webhook" : null
}

# ---- Workload Identity Federation (enable_wif=true 時のみ値が入る) ----

output "wif_provider" {
  description = "GitHub Actions repo Variable WIF_PROVIDER に設定する値。"
  value       = var.enable_wif ? google_iam_workload_identity_pool_provider.github[0].name : null
}

output "wif_service_account" {
  description = "GitHub Actions repo Variable TF_PLAN_SA に設定する値。"
  value       = var.enable_wif ? google_service_account.tf_plan[0].email : null
}

output "wif_setup_summary" {
  description = "GitHub repo に登録する Variables（vars）の値。enable_wif=true 後に terraform output で確認。"
  value = var.enable_wif ? {
    WIF_PROVIDER   = google_iam_workload_identity_pool_provider.github[0].name
    TF_PLAN_SA     = google_service_account.tf_plan[0].email
    TFSTATE_BUCKET = var.tfstate_bucket
    GCP_PROJECT_ID = var.project_id
  } : null
}
