# Phase 1 minimal で必要な API のみ有効化する。
# Phase 2+ で aiplatform / sqladmin / workflows / cloudscheduler 等を追加。
#
# `disable_on_destroy = false`: terraform destroy で API 自体は無効化しない。
# 同 project に他リソースが残っていた場合の事故を防ぐ。

resource "google_project_service" "run" {
  service                    = "run.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "cloudbuild" {
  service                    = "cloudbuild.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "artifactregistry" {
  service                    = "artifactregistry.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "firestore" {
  service                    = "firestore.googleapis.com"
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

resource "google_project_service" "iamcredentials" {
  service                    = "iamcredentials.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "logging" {
  service                    = "logging.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "monitoring" {
  service                    = "monitoring.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

# Phase 2-A1: Cloud SQL pgvector の重複検査基盤。
resource "google_project_service" "sqladmin" {
  service                    = "sqladmin.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

# Phase 2-A3: 自動生成バッチ + Vertex AI 利用に必要な API
resource "google_project_service" "aiplatform" {
  service                    = "aiplatform.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "workflows" {
  service                    = "workflows.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "cloudscheduler" {
  service                    = "cloudscheduler.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}
