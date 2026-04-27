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
