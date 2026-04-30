# Phase 2-C3: review-admin-ui Cloud Run service。
#
# 認証認可は App-level Google OAuth + signed session cookie に切り替え (元々は
# Cloud Run direct IAP だったが、個人 GCP project は組織所属なしで IAP brand の
# 自動 provisioning が動かないため変更)。
#
# 設計判断:
# - Cloud Run service は allUsers invoker (パブリック)。アプリ内の OAuth flow と
#   email allowlist で認可するため、未ログインの request は /login にリダイレクト。
# - line-bot と同 image を共有。CMD で uvicorn review_admin_ui.main:app に切替。
# - Cloud SQL Unix socket (/cloudsql/...) を batch と同じパターンで mount。
# - Firestore は ADC + datastore.user role で接続。
# - OAuth client ID / secret / session secret は Secret Manager 管理。
#
# 必要な事前手動作業 (1 度だけ、Console):
#   - OAuth consent screen を Configure (External、test users に operator email を登録)
#   - OAuth 2.0 Client ID (Web application) を作成
#   - 作成した Client ID / Secret を Secret Manager に投入
#   - 詳細: docs/SETUP.md §6.5

resource "google_cloud_run_v2_service" "admin_ui" {
  count = local.deploy_admin_ui ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = local.admin_ui_service_name

  ingress = "INGRESS_TRAFFIC_ALL"

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

      # OAuth callback URL (Cloud Run service URL + /auth/callback)
      # OAuth client の Authorized redirect URIs と一致する必要あり。
      # apply 後に terraform output review_admin_oauth_redirect_url で値を取得し、
      # Console で OAuth client に追加する (deploy 1 サイクル目は値が確定しない
      # ので, /auth/callback を空にしておくと request.url_for で動的生成される)
      env {
        name  = "ADMIN_OAUTH_REDIRECT_URL"
        value = "" # 動的生成 (request.url_for) を許容
      }

      env {
        name = "ADMIN_OAUTH_CLIENT_ID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.admin_oauth_client_id.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "ADMIN_OAUTH_CLIENT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.admin_oauth_client_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "ADMIN_SESSION_SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.admin_session_secret.secret_id
            version = "latest"
          }
        }
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
    google_project_iam_member.admin_ui_cloudsql_client,
    google_project_iam_member.admin_ui_datastore_user,
    google_secret_manager_secret_iam_member.admin_ui_cloudsql_password,
    google_secret_manager_secret_iam_member.admin_ui_oauth_client_id,
    google_secret_manager_secret_iam_member.admin_ui_oauth_client_secret,
    google_secret_manager_secret_iam_member.admin_ui_session_secret,
  ]
}

# パブリック invoker. 認可はアプリ内 OAuth + email allowlist で実施。
resource "google_cloud_run_v2_service_iam_member" "admin_ui_invoker" {
  count = local.deploy_admin_ui ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.admin_ui[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

data "google_project" "this" {
  project_id = var.project_id
}
