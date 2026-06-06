output "service_url" {
  value       = length(google_cloud_run_v2_service.stock) > 0 ? google_cloud_run_v2_service.stock[0].uri : null
  description = "Cloud Run Service の URL。LINE Webhook URL に `<service_url>/api/line/webhook` を登録し、PUBLIC_BASE_URL には `<service_url>` を設定する。"
}

output "service_account_email" {
  value       = google_service_account.service.email
  description = "Cloud Run の SA email。"
}

output "artifact_registry_repo" {
  value       = google_artifact_registry_repository.stock_analysis_line.name
  description = "Artifact Registry repo 名。Cloud Build で image を push する先。"
}

output "secret_ids" {
  value = {
    line_channel_secret       = google_secret_manager_secret.line_channel_secret.secret_id
    line_channel_access_token = google_secret_manager_secret.line_channel_access_token.secret_id
    claude_code_oauth_token   = google_secret_manager_secret.claude_code_oauth_token.secret_id
    brave_api_key             = google_secret_manager_secret.brave_api_key.secret_id
  }
  description = "Secret Manager の secret ID 一覧。値はすべて手動投入 (gcloud secrets versions add)。"
}
