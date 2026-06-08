# stock-analysis-agent deploy で必要な API を有効化する。
#
# `disable_on_destroy = false`: terraform destroy で API 自体は無効化しない。
# 同 project で他 agent (driving-license-bot / fujisawa-* / piyolog) が稼働中のため。

resource "google_project_service" "run" {
  service                    = "run.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "artifactregistry" {
  service                    = "artifactregistry.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "secretmanager" {
  service                    = "secretmanager.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "iam" {
  service                    = "iam.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "cloudbuild" {
  service                    = "cloudbuild.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "sqladmin" {
  service                    = "sqladmin.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "cloudtasks" {
  service                    = "cloudtasks.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}
