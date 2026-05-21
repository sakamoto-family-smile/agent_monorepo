# Phase 4-2h step 3: Cloud Run Jobs × 7。
#
# 設計判断:
# - 同一 image を全 7 Job で共有 (Dockerfile が 4 extras + cli.py 同梱、step 1)
# - args で `<job_name>` を渡す。`--round` / `--current-year` は locals.etl_jobs で配線
# - Cloud SQL connector で Unix socket 接続 (`/cloudsql/<connection_name>`)
#   asyncpg は host が `/` 始まりだと socket と認識する
# - Secret Manager から env を注入 (db_password / user_agent / vertex_project)
# - timeout / cpu / memory は variables で調整可能 (weekly_crawl は 1,100 URL × 3s)
# - wayback_backfill だけ `wayback_backfill_enabled=false` (default) で skip 状態
#
# image が空文字列なら deploy しない (chicken-and-egg 対策、Dockerfile build & push 前)。

resource "google_cloud_run_v2_job" "etl" {
  for_each = local.deploy_jobs ? local.etl_jobs : {}

  project  = var.project_id
  location = var.region
  name     = each.value.name

  labels = local.labels

  template {
    template {
      service_account = local.sa_etl_email
      timeout         = "${var.etl_job_task_timeout_seconds}s"
      max_retries     = var.etl_job_max_retries

      # Cloud SQL Unix socket 接続
      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [var.shared_cloudsql_instance_connection_name]
        }
      }

      containers {
        image = var.etl_image
        args  = each.value.args

        resources {
          limits = {
            cpu    = var.etl_job_cpu
            memory = var.etl_job_memory
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }

        # ─── DB 接続 ───────────────────────────────────────────────
        env {
          name  = "FUJISAWA_ETL_DB_HOST"
          value = "/cloudsql/${var.shared_cloudsql_instance_connection_name}"
        }
        env {
          name  = "FUJISAWA_ETL_DB_USER"
          value = local.cloudsql_etl_user_name
        }
        env {
          name  = "FUJISAWA_ETL_DB_NAME"
          value = local.cloudsql_database_name
        }
        env {
          name = "FUJISAWA_ETL_DB_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.db_password.secret_id
              version = "latest"
            }
          }
        }

        # ─── HTTP fetcher ──────────────────────────────────────────
        env {
          name = "FUJISAWA_ETL_USER_AGENT"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.user_agent.secret_id
              version = "latest"
            }
          }
        }
        env {
          name  = "FUJISAWA_ETL_MIN_INTERVAL_SEC"
          value = tostring(var.etl_min_interval_sec)
        }
        env {
          name  = "FUJISAWA_ETL_MIN_INTERVAL_SEC_HEAD"
          value = tostring(var.etl_min_interval_sec_head)
        }

        # ─── Vertex AI ─────────────────────────────────────────────
        env {
          name = "FUJISAWA_ETL_VERTEX_PROJECT_ID"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.vertex_project.secret_id
              version = "latest"
            }
          }
        }
        env {
          name  = "FUJISAWA_ETL_VERTEX_LOCATION"
          value = var.vertex_location
        }

        # ─── PdfArchive (GCS) ──────────────────────────────────────
        env {
          name  = "FUJISAWA_ETL_PDF_ARCHIVE_BACKEND"
          value = "gcs"
        }
        env {
          name  = "FUJISAWA_ETL_PDF_ARCHIVE_BUCKET"
          value = google_storage_bucket.pdf_archive.name
        }

        # ─── Job-specific URLs (空文字列 OK、各 Job が必要分のみ参照) ─
        env {
          name  = "FUJISAWA_ETL_SITEMAP_URL"
          value = var.etl_sitemap_url
        }
        env {
          name  = "FUJISAWA_ETL_AUTHORIZED_FACILITIES_URL"
          value = var.etl_authorized_facilities_url
        }
        env {
          name  = "FUJISAWA_ETL_UNAUTHORIZED_FACILITIES_URL"
          value = var.etl_unauthorized_facilities_url
        }
        env {
          name  = "FUJISAWA_ETL_NAVI_PDF_URL"
          value = var.etl_navi_pdf_url
        }
        env {
          name  = "FUJISAWA_ETL_ADMISSION_PDF_URL_1ST"
          value = var.etl_admission_pdf_url_1st
        }
        env {
          name  = "FUJISAWA_ETL_ADMISSION_PDF_URL_2ND"
          value = var.etl_admission_pdf_url_2nd
        }
        env {
          name  = "FUJISAWA_ETL_ADMISSION_YEAR"
          value = tostring(var.etl_admission_year)
        }

        # ─── Logging ──────────────────────────────────────────────
        env {
          name  = "GOOGLE_CLOUD_PROJECT"
          value = var.project_id
        }
      }
    }
  }

  lifecycle {
    # image はデプロイパイプラインで `gcloud run jobs update` で差し替えるので、
    # terraform はそれを無視する (drift しても OK)。
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
  }

  depends_on = [
    google_project_service.run,
    google_project_service.sqladmin,
    google_project_iam_member.etl_cloudsql_client,
    google_project_iam_member.etl_aiplatform_user,
    google_secret_manager_secret_iam_member.etl_db_password,
    google_secret_manager_secret_iam_member.etl_user_agent,
    google_secret_manager_secret_iam_member.etl_vertex_project,
    google_storage_bucket_iam_member.etl_pdf_archive_admin,
  ]
}

# Scheduler / 手動 invoke 用に Cloud Run Job invoker 権限を付与
resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  for_each = local.deploy_jobs ? local.etl_jobs : {}

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.etl[each.key].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}
