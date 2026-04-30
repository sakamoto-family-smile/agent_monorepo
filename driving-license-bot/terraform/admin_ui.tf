# Phase 2-C3: review-admin-ui Cloud Run service (IAP 直接適用)。
#
# 設計判断:
# - HTTPS LB を介さない Cloud Run direct IAP を採用 (2024 GA)。
#   標準 Cloud Run URL でブラウザから IAP の Google ログインが走る。
#   ドメイン / SSL 証明書 / LB / serverless NEG 不要。
# - line-bot と同 image を共有。CMD で uvicorn review_admin_ui.main:app に切替。
# - Cloud SQL Unix socket (/cloudsql/...) を batch と同じパターンで mount。
# - Firestore は ADC + datastore.user role で接続。
# - allowlist 外は IAP が 403 → アプリ側の email check も fail-closed で二段防御。
#
# 必要な事前手動作業 (1 度だけ、Console):
#   - OAuth consent screen を Configure (External / unverified でも個人利用は OK)
#   - 上記後、IAP brand が project に作られる (auto)
#   - 詳細: docs/SETUP.md §6.5

resource "google_cloud_run_v2_service" "admin_ui" {
  count    = local.deploy_admin_ui ? 1 : 0
  provider = google-beta # iap_enabled は google-beta provider のみ

  project  = var.project_id
  location = var.region
  name     = local.admin_ui_service_name

  ingress     = "INGRESS_TRAFFIC_ALL"
  iap_enabled = true

  # Provider 6.x で default true。dev/PoC では teardown を妨げないよう
  # var.deletion_protection (既定 false) に追従。
  deletion_protection = var.deletion_protection

  labels = local.labels

  template {
    service_account = local.sa_admin_ui_email

    scaling {
      min_instance_count = var.review_admin_min_instances
      max_instance_count = var.review_admin_max_instances
    }

    containers {
      image   = var.review_admin_image
      command = ["uvicorn"]
      args = [
        "review_admin_ui.main:app",
        "--host=0.0.0.0",
        "--port=8080",
      ]

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.review_admin_cpu
          memory = var.review_admin_memory
        }
      }

      env {
        name  = "ENV"
        value = "gcp"
      }
      env {
        name  = "ADMIN_SERVICE_NAME"
        value = local.admin_ui_service_name
      }
      env {
        name  = "ADMIN_DEV_BYPASS"
        value = "false"
      }
      env {
        name  = "ADMIN_ALLOWED_EMAILS"
        value = join(",", var.review_admin_allowed_emails)
      }
      # IAP audience: Cloud Run direct IAP の場合、JWT の aud claim は
      # /projects/<NUMBER>/global/backendServices/<UID> 形式 (LB 介在時) ではなく
      # Cloud Run service URL になるケースがある。値は deploy 後に
      # `terraform output review_admin_iap_audience` で確認 + 必要なら手動更新。
      # 既定では service URL を使用 (一致しない場合は network tab で確認可能)。
      env {
        name  = "ADMIN_IAP_AUDIENCE"
        value = "/projects/${data.google_project.this.number}/global/backendServices/${local.admin_ui_service_name}"
      }

      # アプリ層 (app.config.settings) が読む env
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "REPOSITORY_BACKEND"
        value = "firestore"
      }
      env {
        name  = "QUESTION_BANK_BACKEND"
        value = "pgvector"
      }
      env {
        name  = "ANALYTICS_DATA_DIR"
        value = "/tmp/data"
      }
      env {
        name  = "CLOUDSQL_HOST"
        value = "/cloudsql/${google_sql_database_instance.main.connection_name}"
      }
      env {
        name  = "CLOUDSQL_PORT"
        value = "5432"
      }
      env {
        name  = "CLOUDSQL_DB"
        value = local.cloudsql_database_name
      }
      env {
        name  = "CLOUDSQL_USER"
        value = local.cloudsql_user_name
      }

      env {
        name = "CLOUDSQL_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.cloudsql_password.secret_id
            version = "latest"
          }
        }
      }

      startup_probe {
        http_get {
          path = "/healthz"
        }
        initial_delay_seconds = 5
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 6
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    timeout = "60s"
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_project_service.run,
    google_project_service.iap,
    google_project_iam_member.admin_ui_cloudsql_client,
    google_project_iam_member.admin_ui_datastore_user,
    google_secret_manager_secret_iam_member.admin_ui_cloudsql_password,
  ]
}

data "google_project" "this" {
  project_id = var.project_id
}
