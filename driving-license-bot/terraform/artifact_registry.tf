# Docker image (line-bot) を push する Artifact Registry repo。

resource "google_artifact_registry_repository" "main" {
  project       = var.project_id
  location      = var.region
  repository_id = var.ar_repo_name
  format        = "DOCKER"
  description   = "driving-license-bot Docker images"

  labels = local.labels

  depends_on = [google_project_service.artifactregistry]
}

# Cloud Build SA が push できる権限。
# Cloud Build はデフォルト SA `<projectnumber>@cloudbuild.gserviceaccount.com` を
# 使うが、本 PR では明示せず、デプロイ手順 (cloudbuild.yaml) で IAM を確認する形。
# Cloud Run 起動時の image pull は run-service-agent が自動で読めるため設定不要。
