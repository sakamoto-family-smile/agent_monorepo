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

# Secret Manager
output "secret_names" {
  value = {
    line_channel_secret       = google_secret_manager_secret.line_channel_secret.secret_id
    line_channel_access_token = google_secret_manager_secret.line_channel_access_token.secret_id
    line_login_channel_secret = google_secret_manager_secret.line_login_channel_secret.secret_id
    operator_user_ids         = google_secret_manager_secret.operator_user_ids.secret_id
  }
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
