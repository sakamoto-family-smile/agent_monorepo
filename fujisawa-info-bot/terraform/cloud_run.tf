# Cloud Run Service: fujisawa-info-bot
#
# var.image が空文字列なら作らない (chicken-and-egg: image を Cloud Build で
# push してから 2 回目 apply で deploy する)。 driving-license-bot と同パターン。
#
# webhook の public 公開:
# - LINE Platform は webhook を任意 IP から POST してくる → allUsers を invoker に
#   する必要がある (ingress=ALL + IAM の allUsers run.invoker)
# - 署名検証 (HMAC-SHA256) で偽 webhook を排除する責任は app 側

resource "google_cloud_run_v2_service" "info_bot" {
  count = local.deploy_service ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = var.service_name

  ingress = "INGRESS_TRAFFIC_ALL"

  deletion_protection = false

  labels = local.labels

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
        startup_cpu_boost = true
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      # ─── LINE secrets (Secret Manager 経由) ──────────────────────
      env {
        name = "FUJISAWA_INFO_BOT_LINE_CHANNEL_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.line_channel_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "FUJISAWA_INFO_BOT_LINE_CHANNEL_ACCESS_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.line_channel_access_token.secret_id
            version = "latest"
          }
        }
      }

      # ─── LLM 設定 ─────────────────────────────────────────────
      env {
        name  = "FUJISAWA_INFO_BOT_LLM_PROVIDER"
        value = var.llm_provider
      }
      env {
        name  = "FUJISAWA_INFO_BOT_GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "FUJISAWA_INFO_BOT_VERTEX_REGION"
        value = var.vertex_region
      }
      env {
        name  = "FUJISAWA_INFO_BOT_ANTHROPIC_MODEL"
        value = var.anthropic_model
      }
      env {
        name  = "FUJISAWA_INFO_BOT_GEMINI_MODEL"
        value = var.gemini_model
      }

      # ─── KB (pgvector via Cloud SQL Auth Proxy unix socket) ────
      env {
        name  = "FUJISAWA_INFO_BOT_KB_STORE_MODE"
        value = "pgvector"
      }
      env {
        name  = "FUJISAWA_INFO_BOT_EMBEDDING_PROVIDER"
        value = "vertex"
      }
      env {
        name  = "FUJISAWA_INFO_BOT_CLOUD_SQL_HOST"
        value = "/cloudsql/${var.shared_cloudsql_instance_connection_name}"
      }
      env {
        name  = "FUJISAWA_INFO_BOT_CLOUD_SQL_USER"
        value = local.cloudsql_consumer_user_name
      }
      env {
        name  = "FUJISAWA_INFO_BOT_CLOUD_SQL_DATABASE"
        value = var.kb_db_name
      }
      env {
        name = "FUJISAWA_INFO_BOT_CLOUD_SQL_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.kb_db_password.secret_id
            version = "latest"
          }
        }
      }

      # ─── Feature flags ────────────────────────────────────────
      env {
        name  = "FUJISAWA_INFO_BOT_RAG_ENABLED"
        value = "true"
      }
      env {
        name  = "FUJISAWA_INFO_BOT_RAG_TOP_K"
        value = tostring(var.rag_top_k)
      }
    }
  }

  lifecycle {
    # image はデプロイパイプラインで `gcloud run services update` で差し替えるので、
    # terraform は image change を無視する (drift しても OK)。
    # fujisawa-platform / driving-license-bot と同パターン。
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }

  depends_on = [
    google_project_service.run,
    google_project_service.sqladmin,
    google_project_iam_member.service_cloudsql_client,
    google_project_iam_member.service_aiplatform_user,
    google_secret_manager_secret_iam_member.service_line_channel_secret,
    google_secret_manager_secret_iam_member.service_line_channel_access_token,
    google_secret_manager_secret_iam_member.service_kb_db_password,
    google_secret_manager_secret_version.kb_db_password,
    google_sql_user.consumer,
  ]
}

# LINE webhook は public access が必要 (LINE Platform は任意 IP から POST する)
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count = local.deploy_service ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.info_bot[0].location
  name     = google_cloud_run_v2_service.info_bot[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
