################################################################################
# Service Account `sa-piyolog` — Cloud Run service が背負う SA。
#
# 必要な権限:
#   - roles/cloudsql.client          Cloud SQL connector で connect
#   - roles/secretmanager.secretAccessor 各 secret の `latest` version を読む
#   - roles/artifactregistry.reader  Cloud Run が image を pull
#
# 注意: Cloud Run service 自体は TF 管理外 (deploy_cloud_run.sh で作る)。
#       service への SA 紐付けは deploy script 側で `--service-account=...` で行う。
################################################################################

resource "google_service_account" "piyolog" {
  project      = var.project_id
  account_id   = local.sa_piyolog_id
  display_name = "piyolog-analytics Cloud Run service"
  description  = "Used by Cloud Run service to access Cloud SQL + Secret Manager."
}

# Cloud SQL connector
resource "google_project_iam_member" "piyolog_cloud_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.piyolog.email}"
}

# Secret Manager (3 個の secret に対する個別 binding)
resource "google_secret_manager_secret_iam_member" "piyolog_line_channel_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.line_channel_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.piyolog.email}"
}

resource "google_secret_manager_secret_iam_member" "piyolog_line_channel_access_token" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.line_channel_access_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.piyolog.email}"
}

resource "google_secret_manager_secret_iam_member" "piyolog_database_url" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.database_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.piyolog.email}"
}

# Artifact Registry pull
resource "google_artifact_registry_repository_iam_member" "piyolog_ar_reader" {
  project    = var.project_id
  location   = google_artifact_registry_repository.piyolog.location
  repository = google_artifact_registry_repository.piyolog.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.piyolog.email}"
}
