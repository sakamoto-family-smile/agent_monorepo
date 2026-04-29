# Phase 1: sa-line-bot
# Phase 2-A3: sa-batch (Cloud Run Job) / sa-workflow (Workflows) / sa-scheduler (Scheduler)
# Phase 2-C3 以降で sa-admin-ui を追加予定。

resource "google_service_account" "line_bot" {
  project      = var.project_id
  account_id   = local.sa_line_bot_id
  display_name = "driving-license-bot LINE webhook service"
  description  = "Cloud Run line-bot-service が利用する SA。Firestore RW + Secret accessor。"

  depends_on = [google_project_service.iam]
}

# ---- project-level role bindings (sa-line-bot 用) ----

# Firestore RW: Phase 1 のセッション・ユーザー・履歴管理
resource "google_project_iam_member" "line_bot_datastore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${local.sa_line_bot_email}"
}

# Cloud Logging への書き込み（Cloud Run の logger からも自動だが明示）
resource "google_project_iam_member" "line_bot_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${local.sa_line_bot_email}"
}

# Cloud Monitoring への custom metric 書き込み（pool 監視等は Phase 2+ だが、
# 起動時の uptime ping に必要）
resource "google_project_iam_member" "line_bot_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${local.sa_line_bot_email}"
}

# ---- Phase 2-A3: sa-batch (Cloud Run Job 自動生成バッチ) ----

resource "google_service_account" "batch" {
  project      = var.project_id
  account_id   = local.sa_batch_id
  display_name = "driving-license-bot batch generation"
  description  = "Cloud Run Job が利用する SA。Vertex AI / Cloud SQL / Firestore / Secrets RW。"

  depends_on = [google_project_service.iam]
}

# Vertex AI: Claude / Gemini / Embedding を呼ぶ
resource "google_project_iam_member" "batch_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${local.sa_batch_email}"
}

# Cloud SQL: pgvector に接続（Auth Proxy / sidecar 経由）
resource "google_project_iam_member" "batch_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${local.sa_batch_email}"
}

# Firestore: 問題本文 / 解説 / メタを書き込む
resource "google_project_iam_member" "batch_datastore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${local.sa_batch_email}"
}

# Cloud Logging
resource "google_project_iam_member" "batch_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${local.sa_batch_email}"
}

# Cloud Monitoring の custom metric (question_pool_size 等)
resource "google_project_iam_member" "batch_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${local.sa_batch_email}"
}

# ---- Phase 2-A3: sa-workflow (Workflows → Cloud Run Job 起動) ----

resource "google_service_account" "workflow" {
  project      = var.project_id
  account_id   = local.sa_workflow_id
  display_name = "driving-license-bot workflows"
  description  = "Workflows が Cloud Run Job (sa-batch) を起動するための SA。"

  depends_on = [google_project_service.iam]
}

# Cloud Run Job を起動するため (jobs.run permission)
resource "google_project_iam_member" "workflow_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${local.sa_workflow_email}"
}

# Workflow の logs 書き込み
resource "google_project_iam_member" "workflow_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${local.sa_workflow_email}"
}

# Cloud Run Job は sa-batch として実行されるため、workflow が sa-batch を actAs する必要がある
resource "google_service_account_iam_member" "workflow_act_as_batch" {
  service_account_id = google_service_account.batch.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${local.sa_workflow_email}"
}

# ---- Phase 2-A3: sa-scheduler (Scheduler → Workflow 起動) ----

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = local.sa_scheduler_id
  display_name = "driving-license-bot scheduler"
  description  = "Cloud Scheduler が Workflow を nightly 起動するための SA。"

  depends_on = [google_project_service.iam]
}

# Workflow を起動するため
resource "google_project_iam_member" "scheduler_workflows_invoker" {
  project = var.project_id
  role    = "roles/workflows.invoker"
  member  = "serviceAccount:${local.sa_scheduler_email}"
}

# ---- Phase 2-C3: sa-admin-ui (review-admin-ui Cloud Run 用) ----

resource "google_service_account" "admin_ui" {
  project      = var.project_id
  account_id   = local.sa_admin_ui_id
  display_name = "driving-license-bot review admin UI"
  description  = "Cloud Run review-admin-ui が利用する SA。pgvector / Firestore RW + secret accessor。"

  depends_on = [google_project_service.iam]
}

# Cloud SQL: pgvector に list_by_status / update_status を発行
resource "google_project_iam_member" "admin_ui_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.admin_ui.email}"
}

# Firestore: 問題本文 (Question) を読む
resource "google_project_iam_member" "admin_ui_datastore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.admin_ui.email}"
}

# Cloud Logging
resource "google_project_iam_member" "admin_ui_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.admin_ui.email}"
}

# Cloud Monitoring (uptime ping や custom metric)
resource "google_project_iam_member" "admin_ui_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.admin_ui.email}"
}
