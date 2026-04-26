################################################################################
# Artifact Registry — `piyolog-analytics:<tag>` Docker image の置き場。
#
# image URI:
#   ${region}-docker.pkg.dev/${project_id}/${ar_repo_name}/piyolog-analytics:<tag>
################################################################################

resource "google_artifact_registry_repository" "piyolog" {
  project       = var.project_id
  location      = var.region
  repository_id = var.ar_repo_name
  format        = "DOCKER"
  description   = "piyolog-analytics Cloud Run service image"

  labels = {
    component = "piyolog-analytics"
  }
}
