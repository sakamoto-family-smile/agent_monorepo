# Artifact Registry repo: stock-analysis-line Cloud Run Service image を格納。

resource "google_artifact_registry_repository" "stock_analysis_line" {
  location      = var.region
  repository_id = local.artifact_registry_repo
  description   = "stock-analysis-agent (LINE) Cloud Run Service image"
  format        = "DOCKER"
  labels        = local.labels

  depends_on = [google_project_service.artifactregistry]
}
