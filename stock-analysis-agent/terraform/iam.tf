# Cloud Run Service の SA + IAM bindings。
#
# 必要権限 (MVP は最小):
# - Secret Manager Accessor (LINE secrets + CLAUDE_CODE_OAUTH_TOKEN + BRAVE_API_KEY)
#   → secrets.tf で secret 単位に付与
# - Logging Writer
# - Artifact Registry Reader (image pull)
#
# Cloud SQL / Vertex AI は MVP では使わない (ephemeral SQLite + Anthropic OAuth token)。

resource "google_service_account" "service" {
  account_id   = local.sa_service_name
  display_name = "stock-analysis-line Cloud Run Service"

  depends_on = [google_project_service.iam]
}

resource "google_project_iam_member" "service_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.service.email}"
}

resource "google_project_iam_member" "service_artifact_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.service.email}"
}

# Cloud SQL 接続 (PROPOSAL-0011 P2-B: shared-pg connector)
resource "google_project_iam_member" "service_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.service.email}"
}
