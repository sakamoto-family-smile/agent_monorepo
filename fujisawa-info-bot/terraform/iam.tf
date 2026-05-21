# Cloud Run Service の SA + IAM bindings。
#
# 必要権限:
# - Cloud SQL Client (fujisawa_kb_db 接続)
# - Vertex AI User (Claude via Vertex)
# - Secret Manager Accessor (LINE secrets + DB password)
# - Logging Writer
# - Artifact Registry Reader (image pull)

resource "google_service_account" "service" {
  account_id   = local.sa_service_name
  display_name = "fujisawa-info-bot Cloud Run Service"

  depends_on = [google_project_service.iam]
}

resource "google_project_iam_member" "service_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.service.email}"
}

resource "google_project_iam_member" "service_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.service.email}"
}

resource "google_project_iam_member" "service_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.service.email}"
}

# Artifact Registry の image pull
resource "google_project_iam_member" "service_artifact_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.service.email}"
}
