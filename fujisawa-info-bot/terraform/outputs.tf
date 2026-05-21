output "service_url" {
  value       = length(google_cloud_run_v2_service.info_bot) > 0 ? google_cloud_run_v2_service.info_bot[0].uri : null
  description = "Cloud Run Service の URL。 LINE Developers Console > Webhook URL に `<service_url>/webhook` を登録する。"
}

output "service_account_email" {
  value       = google_service_account.service.email
  description = "fujisawa-info-bot Cloud Run の SA email。 fujisawa-platform 側の `consumer_service_account_emails` 変数に追加して GCS bucket viewer を付与する。"
}

output "artifact_registry_repo" {
  value       = google_artifact_registry_repository.fujisawa_info_bot.name
  description = "Artifact Registry repo 名。 Cloud Build で image を push する先。"
}

output "secret_ids" {
  value = {
    line_channel_secret       = google_secret_manager_secret.line_channel_secret.secret_id
    line_channel_access_token = google_secret_manager_secret.line_channel_access_token.secret_id
    kb_db_password            = google_secret_manager_secret.kb_db_password.secret_id
  }
  description = "Secret Manager 上の secret ID 一覧。 LINE secrets は手動投入。 DB password は terraform 自動投入済。"
}

output "cloudsql_consumer_user" {
  value       = google_sql_user.consumer.name
  description = "fujisawa_kb_db の consumer 用 user 名。 psql で `GRANT SELECT ON pages TO <user>` を別途流す (docs/SETUP.md §4)。"
}
