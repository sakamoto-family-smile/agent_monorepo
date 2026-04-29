# Cloud Run service: line-bot-service。
# image push 後に `terraform apply -var line_bot_image=...` で deploy。
# `line_bot_image=""` の初回 apply ではこの service を作らない（chicken-and-egg 回避）。

locals {
  deploy_line_bot = length(trimspace(var.line_bot_image)) > 0
}

resource "google_cloud_run_v2_service" "line_bot" {
  count = local.deploy_line_bot ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = local.line_bot_service_name

  ingress = "INGRESS_TRAFFIC_ALL"

  labels = local.labels

  template {
    service_account = local.sa_line_bot_email

    scaling {
      min_instance_count = var.line_bot_min_instances
      max_instance_count = var.line_bot_max_instances
    }

    containers {
      image = var.line_bot_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.line_bot_cpu
          memory = var.line_bot_memory
        }
      }

      env {
        name  = "ENV"
        value = "gcp"
      }
      env {
        name  = "SERVICE_NAME"
        value = "driving-license-bot-line"
      }
      env {
        name  = "REPOSITORY_BACKEND"
        value = "firestore"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "FIRESTORE_DATABASE"
        value = "(default)"
      }
      # Cloud Run は `/tmp` 以外 read-only。analytics-platform の
      # JsonlSink 出力先を `/tmp/data` に逃がす（再起動で消えるが Phase 1 では許容）。
      env {
        name  = "ANALYTICS_DATA_DIR"
        value = "/tmp/data"
      }

      # Phase 2-X1: 出題プールのソース。"seed" (Phase 1 既定) or "bank"。
      env {
        name  = "QUESTION_POOL_SOURCE"
        value = var.line_bot_pool_source
      }
      # bank プール時は pgvector (Cloud SQL) と Firestore に接続が必要
      dynamic "env" {
        for_each = var.line_bot_pool_source == "bank" ? [1] : []
        content {
          name  = "QUESTION_BANK_BACKEND"
          value = "pgvector"
        }
      }
      dynamic "env" {
        for_each = var.line_bot_pool_source == "bank" ? [1] : []
        content {
          name  = "CLOUDSQL_HOST"
          value = "/cloudsql/${google_sql_database_instance.main.connection_name}"
        }
      }
      dynamic "env" {
        for_each = var.line_bot_pool_source == "bank" ? [1] : []
        content {
          name  = "CLOUDSQL_PORT"
          value = "5432"
        }
      }
      dynamic "env" {
        for_each = var.line_bot_pool_source == "bank" ? [1] : []
        content {
          name  = "CLOUDSQL_DB"
          value = local.cloudsql_database_name
        }
      }
      dynamic "env" {
        for_each = var.line_bot_pool_source == "bank" ? [1] : []
        content {
          name  = "CLOUDSQL_USER"
          value = local.cloudsql_user_name
        }
      }
      dynamic "env" {
        for_each = var.line_bot_pool_source == "bank" ? [1] : []
        content {
          name = "CLOUDSQL_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.cloudsql_password.secret_id
              version = "latest"
            }
          }
        }
      }

      # LINE secrets は Secret Manager → env に注入
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

      # 起動時のヘルスチェック
      startup_probe {
        http_get {
          path = "/healthz"
        }
        initial_delay_seconds = 5
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 6
      }

      liveness_probe {
        http_get {
          path = "/healthz"
        }
        period_seconds  = 30
        timeout_seconds = 5
      }

      # bank プール時のみ Cloud SQL Unix socket をマウント
      dynamic "volume_mounts" {
        for_each = var.line_bot_pool_source == "bank" ? [1] : []
        content {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
    }

    # bank プール時のみ cloud_sql_instance volume を定義
    dynamic "volumes" {
      for_each = var.line_bot_pool_source == "bank" ? [1] : []
      content {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.main.connection_name]
        }
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
    google_secret_manager_secret_iam_member.line_bot_channel_secret,
    google_secret_manager_secret_iam_member.line_bot_channel_access_token,
    google_firestore_database.default,
  ]
}

# LINE Webhook はパブリックなので allUsers に invoker 付与。
# 認証は X-Line-Signature の HMAC で実質的な access control。
resource "google_cloud_run_v2_service_iam_member" "line_bot_invoker" {
  for_each = local.deploy_line_bot ? toset(var.line_bot_invoker_members) : toset([])

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.line_bot[0].name
  role     = "roles/run.invoker"
  member   = each.value
}
