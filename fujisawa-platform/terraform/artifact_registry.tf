# Phase 4-2h step 2: Artifact Registry (Docker image)。
#
# 設計方針:
# - 1 リポジトリで 1 image (`fujisawa-etl`) を管理。Cloud Run Jobs × 7 はすべて同 image
#   を `--args=<job_name>` で起動 (step 3)。
# - lifecycle で古い image を自動削除 (default 10 個保持)。Cloud Build push のたびに
#   古いものが消える。

resource "google_artifact_registry_repository" "fujisawa_etl" {
  project       = var.project_id
  location      = var.region
  repository_id = local.artifact_registry_repo_id
  format        = "DOCKER"
  description   = "fujisawa-platform ETL Cloud Run Job image"

  labels = local.labels

  dynamic "cleanup_policies" {
    for_each = var.artifact_registry_image_retention_count > 0 ? [1] : []
    content {
      id     = "keep-recent-${var.artifact_registry_image_retention_count}"
      action = "KEEP"
      most_recent_versions {
        keep_count = var.artifact_registry_image_retention_count
      }
    }
  }

  dynamic "cleanup_policies" {
    for_each = var.artifact_registry_image_retention_count > 0 ? [1] : []
    content {
      id     = "delete-old"
      action = "DELETE"
      condition {
        older_than = "2592000s" # 30 日
      }
    }
  }

  depends_on = [google_project_service.artifactregistry]
}

# Cloud Run Job 側 (step 3 で作成) に image pull 権限を付与する。
# Cloud Run の Service Agent (`service-<projectnum>@serverless-robot-prod.iam.gserviceaccount.com`)
# は同 project 内 Artifact Registry を自動で pull 可能なため、追加 IAM は通常不要。
# 明示的に開発者用の writer ロールを付ける場合は別途 `google_artifact_registry_repository_iam_member` で。
