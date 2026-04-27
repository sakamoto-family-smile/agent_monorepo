# Phase 1 minimal: line-bot-service 用の SA のみ。
# Phase 2 以降で sa-agent / sa-batch / sa-workflow / sa-scheduler / sa-admin-ui を追加。

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
