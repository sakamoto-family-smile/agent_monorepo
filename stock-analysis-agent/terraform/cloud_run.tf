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

      # ─── analytics (MVP は local backend。pubsub 切替は P2) ────────
      env {
        name  = "ANALYTICS_ENABLED"
        value = "true"
      }
      env {
        name  = "ANALYTICS_STORAGE_BACKEND"
        value = "local"
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
    google_secret_manager_secret_iam_member.service_line_channel_secret,
    google_secret_manager_secret_iam_member.service_line_channel_access_token,
    google_secret_manager_secret_iam_member.service_claude_code_oauth_token,
    google_secret_manager_secret_iam_member.service_brave_api_key,
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
