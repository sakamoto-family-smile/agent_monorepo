################################################################################
# Step 1 (部分): Artifact Registry — dbt Cloud Run Job image (Step 7) の置き場
#
# image URI:
#   ${region}-docker.pkg.dev/${project_id}/${repo_name}/analytics-platform-dbt:<tag>
################################################################################

resource "google_artifact_registry_repository" "dbt" {
  project       = var.project_id
  location      = var.region
  repository_id = var.ar_repo_name
  format        = "DOCKER"
  description   = "analytics-platform dbt Cloud Run Job image"

  labels = {
    component = "analytics-platform"
  }
}
