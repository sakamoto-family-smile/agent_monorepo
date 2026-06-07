# Cloud Run Service: stock-analysis-line (PROPOSAL-0011 P1)。
#
# var.image が空文字列なら作らない (chicken-and-egg: image を Cloud Build で push
# してから 2 回目 apply で deploy する)。fujisawa-info-bot / driving-license-bot 同型。
#
# webhook の public 公開:
# - LINE Platform は webhook を任意 IP から POST → allUsers を invoker にする必要がある
#   (ingress=ALL + IAM allUsers run.invoker)。偽 webhook 排除は app の署名検証が担う。
#
# BackgroundTasks (ack→push) を確実に完了させるため:
# - min_instances=1 かつ cpu_idle=false (CPU always-allocated)。レスポンス返却後も
#   分析 background task が走り続けられる。

resource "google_cloud_run_v2_service" "stock" {
  count = local.deploy_service ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = var.service_name

  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels

  template {
    service_account = google_service_account.service.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    timeout = "${var.service_request_timeout_seconds}s"

    # Cloud SQL connector (UNIX socket /cloudsql/<connection_name>)
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
          cpu    = var.service_cpu
          memory = var.service_memory
        }
        # CPU always-allocated: レスポンス後の BackgroundTasks を止めないため必須。
        cpu_idle          = false
        startup_cpu_boost = true
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      # ─── LINE secrets (Secret Manager) ───────────────────────────
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

      # ─── LLM / 検索 secrets ──────────────────────────────────────
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

      # ─── アプリ設定 ───────────────────────────────────────────────
      env {
        name  = "APP_ENV"
        value = "prod"
      }
      env {
        name  = "LOG_LEVEL"
        value = var.log_level
      }
      env {
        name  = "PUBLIC_BASE_URL"
        value = var.public_base_url
      }
      env {
        name  = "FAMILY_USER_IDS"
        value = var.family_user_ids
      }
      env {
        name  = "ANALYZE_RATE_LIMIT_PER_DAY"
        value = tostring(var.analyze_rate_limit_per_day)
      }

      # ─── analytics (P2-A: pubsub 入口で本番イベントを永続化) ──────
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

      # ─── EDINET (P1 は無効) ──────────────────────────────────────
      env {
        name  = "EDINET_ENABLED"
        value = var.edinet_enabled ? "true" : "false"
      }

      # ─── claude CLI の version 不一致で落ちないよう check を skip ──
      env {
        name  = "CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK"
        value = "1"
      }

      # ─── DB (PROPOSAL-0011 P2-B: shared Cloud SQL Postgres) ──────
      # config.resolved_database_url が DB_HOST/USER/NAME/PASSWORD から
      # postgresql+asyncpg URL を組み立てる (DB_HOST は connector の unix socket)。
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
      # prod はスキーマを alembic で管理: 起動時 migrate + init_db は seed のみ。
      env {
        name  = "DB_AUTO_CREATE"
        value = "false"
      }
      env {
        name  = "RUN_MIGRATIONS"
        value = "true"
      }
    }
  }

  lifecycle {
    # image はデプロイパイプライン (gcloud run deploy / 2 回目 apply) で差し替える
    # ので terraform は image change を無視する。
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
    google_sql_user.stock,
    google_sql_database.stock,
  ]
}

# LINE webhook は public access が必要 (LINE Platform は任意 IP から POST する)
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count = local.deploy_service ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.stock[0].location
  name     = google_cloud_run_v2_service.stock[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
