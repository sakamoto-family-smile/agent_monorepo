# Phase 2-B2: 自動生成バッチ用の Cloud Run Job。
#
# Workflow → Cloud Run Job (sa-batch) で実行される。Job 内で:
#   1. build_llm_client (gemini or claude) で Question Generator を構築
#   2. build_reviewer_llm_client (Gemini) で Quality Reviewer を構築
#   3. build_embedding_client (text-embedding-004)
#   4. PgvectorQuestionBank に対して dedup 検索 + add
#   5. Firestore に問題本文 / 解説を保存
#
# 設計判断:
# - 同一 image を line-bot service と batch Job で共有（Dockerfile が両方の依存を含む）
# - command/args で起動エントリ差別化: batch は `python -m scripts.run_batch`
# - Cloud SQL は Unix socket (/cloudsql/PROJECT:REGION:INSTANCE) 経由
#   asyncpg は host が `/` で始まると socket と認識
# - LINE secrets は B3 の operator notify で利用予定（投入は A3 で済）

resource "google_cloud_run_v2_job" "batch" {
  count = local.deploy_batch ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = local.batch_job_name

  labels = local.labels

  template {
    template {
      service_account = local.sa_batch_email
      timeout         = "${var.batch_task_timeout_seconds}s"
      max_retries     = var.batch_max_retries

      containers {
        image   = var.batch_image
        command = ["python"]
        args    = ["-m", "scripts.run_batch", "--total", tostring(var.generation_batch_size)]

        resources {
          limits = {
            cpu    = var.batch_cpu
            memory = var.batch_memory
          }
        }

        env {
          name  = "ENV"
          value = "gcp"
        }
        env {
          name  = "SERVICE_NAME"
          value = local.batch_job_name
        }
        env {
          name  = "GOOGLE_CLOUD_PROJECT"
          value = var.project_id
        }
        env {
          name  = "ANTHROPIC_VERTEX_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "CLOUD_ML_REGION"
          value = var.region
        }
        env {
          name  = "AGENT_LLM_PROVIDER"
          value = var.agent_llm_provider
        }
        env {
          name  = "REPOSITORY_BACKEND"
          value = "firestore"
        }
        env {
          name  = "FIRESTORE_DATABASE"
          value = "(default)"
        }
        env {
          name  = "QUESTION_BANK_BACKEND"
          value = "pgvector"
        }
        # Cloud Run /tmp 以外 read-only。analytics-platform の JsonlSink 出力先。
        env {
          name  = "ANALYTICS_DATA_DIR"
          value = "/tmp/data"
        }
        # Cloud SQL Unix socket: /cloudsql/<connection_name>
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
        # B3 で運営者 LINE Push に使う（pool_low_alert 等）
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
          name = "OPERATOR_LINE_USER_IDS"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.operator_user_ids.secret_id
              version = "latest"
            }
          }
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
    }
  }

  depends_on = [
    google_project_service.run,
    google_project_service.aiplatform,
    google_project_iam_member.batch_aiplatform_user,
    google_project_iam_member.batch_cloudsql_client,
    google_project_iam_member.batch_datastore_user,
    google_project_iam_member.batch_log_writer,
    google_secret_manager_secret_iam_member.batch_cloudsql_password,
    google_secret_manager_secret_iam_member.batch_line_channel_access_token,
    google_secret_manager_secret_iam_member.batch_line_channel_secret,
    google_secret_manager_secret_iam_member.batch_operator_user_ids,
  ]
}
