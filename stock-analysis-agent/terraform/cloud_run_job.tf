# EDINET index batch を Cloud Run Job + Cloud Scheduler で日次実行 (PROPOSAL-0011 P3-B)。
#
# Job は webhook/worker と同一イメージで、command を batch モジュールに上書きして
# `edinet_documents` を rolling 窓で upsert する。DB が埋まることで collector の
# 直叩きフォールバック (~7 分) を回避し、分析時の EDINET 取得が ~10 秒で済む。
#
# EDINET 無効時 (var.edinet_enabled=false) は Job / Scheduler を作らない。

resource "google_cloud_run_v2_job" "edinet_index" {
  count = local.deploy_edinet ? 1 : 0

  project             = var.project_id
  location            = var.region
  name                = var.edinet_job_name
  deletion_protection = false
  labels              = local.labels

  template {
    template {
      service_account = google_service_account.service.email
      timeout         = "${var.edinet_job_timeout_seconds}s"
      max_retries     = 1

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [var.shared_cloudsql_instance_connection_name]
        }
      }

      containers {
        image = var.image
        # alembic 適用 (冪等) してから index batch を実行する。
        command = ["sh", "-c"]
        args = [
          "cd /app && alembic upgrade head && python -m batch.edinet_index_etl"
        ]

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }

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
        env {
          name = "EDINET_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.edinet_api_key.secret_id
              version = "latest"
            }
          }
        }
        env {
          name  = "EDINET_DAILY_WINDOW_DAYS"
          value = tostring(var.edinet_daily_window_days)
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
  }

  depends_on = [
    google_project_service.run,
    google_project_service.sqladmin,
    google_secret_manager_secret_iam_member.service_db_password,
    google_secret_manager_secret_iam_member.service_edinet_api_key,
    google_secret_manager_secret_version.db_password,
  ]
}

# scheduler (service SA) が Job を実行できるよう run.invoker を付与。
resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  count = local.deploy_edinet ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.edinet_index[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.service.email}"
}

resource "google_cloud_scheduler_job" "edinet_index" {
  count = local.deploy_edinet ? 1 : 0

  project   = var.project_id
  region    = var.region
  name      = "${var.edinet_job_name}-daily"
  schedule  = var.edinet_index_schedule
  time_zone = "Asia/Tokyo"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${var.edinet_job_name}:run"

    oauth_token {
      service_account_email = google_service_account.service.email
    }
  }

  depends_on = [
    google_project_service.cloudscheduler,
    google_cloud_run_v2_job_iam_member.scheduler_invoker,
  ]
}
