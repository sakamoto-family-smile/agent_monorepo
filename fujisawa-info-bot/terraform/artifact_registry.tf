# Artifact Registry repo: fujisawa-info-bot Cloud Run Service image を格納。
# fujisawa-platform の `fujisawa-etl` repo とは分離 (image 用途が異なる)。

resource "google_artifact_registry_repository" "fujisawa_info_bot" {
  location      = var.region
  repository_id = local.artifact_registry_repo
  description   = "fujisawa-info-bot Cloud Run Service image"
  format        = "DOCKER"
  labels        = local.labels

  depends_on = [google_project_service.artifactregistry]
}
