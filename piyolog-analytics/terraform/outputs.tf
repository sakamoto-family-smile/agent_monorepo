output "cloud_sql_instance_name" {
  description = "Cloud SQL instance name."
  value       = google_sql_database_instance.piyolog.name
}

output "cloud_sql_connection_name" {
  description = "Cloud SQL connection name (project:region:instance). Used by --add-cloudsql-instances."
  value       = google_sql_database_instance.piyolog.connection_name
}

output "cloud_sql_db_name" {
  description = "Database name created inside the instance."
  value       = google_sql_database.piyolog.name
}

output "cloud_sql_db_user" {
  description = "Database user."
  value       = google_sql_user.piyolog.name
}

output "artifact_registry_repo" {
  description = "Artifact Registry repository id."
  value       = google_artifact_registry_repository.piyolog.repository_id
}

output "sa_piyolog_email" {
  description = "Service account for the Cloud Run service. Pass to --service-account=..."
  value       = google_service_account.piyolog.email
}

output "secret_line_channel_secret" {
  description = "Secret Manager id for LINE channel secret. Latest version is mounted as env."
  value       = google_secret_manager_secret.line_channel_secret.secret_id
}

output "secret_line_channel_access_token" {
  description = "Secret Manager id for LINE channel access token."
  value       = google_secret_manager_secret.line_channel_access_token.secret_id
}

output "secret_database_url" {
  description = "Secret Manager id for SQLAlchemy DATABASE_URL."
  value       = google_secret_manager_secret.database_url.secret_id
}

# `make deploy-cloud-run` が読む env を一括出力。
# `terraform output -json env_for_deploy | jq -r 'to_entries[]|"\(.key)=\(.value)"' >> .env.deploy`
output "env_for_deploy" {
  description = "Env values consumed by scripts/deploy_cloud_run.sh."
  value = {
    PIYOLOG_GCP_PROJECT        = var.project_id
    PIYOLOG_AR_LOCATION        = var.region
    PIYOLOG_AR_REPO            = google_artifact_registry_repository.piyolog.repository_id
    PIYOLOG_REGION             = var.region
    PIYOLOG_CLOUD_SQL_INSTANCE = google_sql_database_instance.piyolog.connection_name
    PIYOLOG_CLOUD_RUN_SA       = google_service_account.piyolog.email
  }
}
