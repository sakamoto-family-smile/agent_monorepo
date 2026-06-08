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
    db_password               = google_secret_manager_secret.db_password.secret_id
  }
  description = "Secret Manager の secret ID 一覧。LINE/Claude/Brave は手動投入、db_password は terraform 自動投入済。"
}

output "cloudsql_database" {
  value       = google_sql_database.stock.name
  description = "shared-pg 上に作成した stock 専用 database 名。"
}

output "cloudsql_user" {
  value       = google_sql_user.stock.name
  description = "stock 専用 DB user 名。GRANT は psql で別途流す (terraform/README.md 参照)。"
}

output "worker_url" {
  value       = length(google_cloud_run_v2_service.worker) > 0 ? google_cloud_run_v2_service.worker[0].uri : null
  description = "分析 worker Cloud Run の URL (Cloud Tasks の dispatch 先 + media 配信元)。"
}

output "tasks_queue" {
  value       = google_cloud_tasks_queue.analysis.id
  description = "Cloud Tasks queue のフルパス。"
}

output "tasks_invoker_sa" {
  value       = google_service_account.tasks_invoker.email
  description = "Cloud Tasks OIDC invoker SA (worker が email を検証)。"
}

output "media_bucket" {
  value       = google_storage_bucket.media.name
  description = "チャート/全文 media 配信用 GCS バケット。"
}
