# Cloud Run Service: stock-analysis-worker (PROPOSAL-0011 P3-A)。
#
# Cloud Tasks から OIDC 認証付きで /api/tasks/analyze を叩かれ、分析本体を同期実行
# して LINE Push する。webhook と同一イメージ・同一 runtime SA を使う。
#
# - min=0 / max>1: タスク到着時にスケール、アイドルで 0。並列度は queue の
#   max_concurrent_dispatches が制御。
# - public (allUsers): media (/api/line/image|report) を LINE が取得するため。
#   /api/tasks/analyze は app 内で OIDC token を検証して保護する。
# - request timeout を長め (EDINET 有効化で 1〜5 分。P3-B) に取る。
# - media は GCS backend (複数 instance でも 404 にならない)。
# - スキーマ migration は webhook 側が担当 (RUN_MIGRATIONS=false)。

resource "google_cloud_run_v2_service" "worker" {
  count = local.deploy_worker ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = var.worker_service_name

  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels

  template {
    service_account = google_service_account.service.email

    scaling {
      min_instance_count = var.worker_min_instances
      max_instance_count = var.worker_max_instances
    }

    timeout = "${var.worker_request_timeout_seconds}s"

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [var.shared_cloudsql_instance_connection_name]
      }
    }

    containers {
      image = var.image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.worker_cpu
          memory = var.worker_memory
        }
        startup_cpu_boost = true
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      # ─── secrets ─────────────────────────────────────────────────
      env {
        name = "LINE_CHANNEL_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.line_channel_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "LINE_CHANNEL_ACCESS_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.line_channel_access_token.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "CLAUDE_CODE_OAUTH_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.claude_code_oauth_token.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "BRAVE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.brave_api_key.secret_id
            version = "latest"
          }
        }
      }

      # ─── app 設定 ────────────────────────────────────────────────
      env {
        name  = "APP_ENV"
        value = "prod"
      }
      env {
        name  = "LOG_LEVEL"
        value = var.log_level
      }
      # worker は OIDC 検証のため invoker SA を知る (audience は email 検証で代替)。
      env {
        name  = "TASKS_INVOKER_SA"
        value = google_service_account.tasks_invoker.email
      }

      # ─── media (GCS backend) ─────────────────────────────────────
      env {
        name  = "MEDIA_BACKEND"
        value = "gcs"
      }
      env {
        name  = "MEDIA_GCS_BUCKET"
        value = google_storage_bucket.media.name
      }

      # ─── analytics (pubsub) ──────────────────────────────────────
      env {
        name  = "ANALYTICS_ENABLED"
        value = "true"
      }
      env {
        name  = "ANALYTICS_STORAGE_BACKEND"
        value = var.analytics_storage_backend
      }
      env {
        name  = "ANALYTICS_PUBSUB_TOPIC"
        value = var.analytics_pubsub_topic
      }
      env {
        name  = "ANALYTICS_GCP_PROJECT"
        value = var.project_id
      }

      # ─── EDINET (P3-B) ───────────────────────────────────────────
      env {
        name  = "EDINET_ENABLED"
        value = var.edinet_enabled ? "true" : "false"
      }
      env {
        name  = "EDINET_CODE_CSV_PATH"
        value = local.edinet_code_csv_uri
      }
      env {
        name  = "EDINET_CACHE_BACKEND"
        value = "gcs"
      }
      env {
        name  = "EDINET_CACHE_GCS_BUCKET"
        value = google_storage_bucket.edinet.name
      }
      env {
        name  = "EDINET_CACHE_GCS_PREFIX"
        value = "edinet/"
      }
      # EDINET 有効時のみ API key secret を参照 (無効時は version 不要)。
      dynamic "env" {
        for_each = var.edinet_enabled ? [1] : []
        content {
          name = "EDINET_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.edinet_api_key.secret_id
              version = "latest"
            }
          }
        }
      }
      env {
        name  = "CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK"
        value = "1"
      }

      # ─── DB (shared Cloud SQL) ───────────────────────────────────
      env {
        name  = "DB_HOST"
        value = "/cloudsql/${var.shared_cloudsql_instance_connection_name}"
      }
      env {
        name  = "DB_USER"
        value = var.db_user
      }
      env {
        name  = "DB_NAME"
        value = var.db_name
      }
      env {
        name = "DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_password.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "DB_AUTO_CREATE"
        value = "false"
      }
      # migration は webhook 側で実行 (二重実行を避ける)。
      env {
        name  = "RUN_MIGRATIONS"
        value = "false"
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }

  depends_on = [
    google_project_service.run,
    google_project_service.sqladmin,
    google_project_iam_member.service_cloudsql_client,
    google_secret_manager_secret_iam_member.service_line_channel_secret,
    google_secret_manager_secret_iam_member.service_line_channel_access_token,
    google_secret_manager_secret_iam_member.service_claude_code_oauth_token,
    google_secret_manager_secret_iam_member.service_brave_api_key,
    google_secret_manager_secret_iam_member.service_db_password,
    google_secret_manager_secret_version.db_password,
    google_storage_bucket_iam_member.media_writer,
    google_storage_bucket_iam_member.edinet_writer,
    google_secret_manager_secret_iam_member.service_edinet_api_key,
    google_sql_user.stock,
    google_sql_database.stock,
  ]
}

# media を LINE が取得するため public。/api/tasks/analyze は app 内 OIDC 検証で保護。
resource "google_cloud_run_v2_service_iam_member" "worker_public_invoker" {
  count = local.deploy_worker ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.worker[0].location
  name     = google_cloud_run_v2_service.worker[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
