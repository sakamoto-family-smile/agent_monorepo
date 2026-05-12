# Phase 4-2h step 2: Service Account + IAM bindings。
#
# 設計方針 (proposal 0003 §4.5.3):
# - ETL Cloud Run Jobs は `sa-fujisawa-etl` で動く (Workload Identity 経由)
# - DB 書き込み権限 (`etl_role`) は PostgreSQL ROLE 側で制御 (psql で GRANT)
# - GCP IAM では Cloud SQL Client / Secret Accessor / GCS Object Admin (PdfArchive) /
#   AI Platform User (Vertex Embedding) を付与する
# - Artifact Registry の image pull 権限は Cloud Run の SA に自動付与される
#   想定 (Cloud Run service が同 project 内なら明示不要)

# ─────────────────────────────────────────────────────────────────────
# ETL Service Account
# ─────────────────────────────────────────────────────────────────────

resource "google_service_account" "etl" {
  project      = var.project_id
  account_id   = local.sa_etl_id
  display_name = "fujisawa-platform ETL Cloud Run Job"
  description  = "Cloud Run Jobs that fetch / parse / upsert fujisawa city data. Phase 4-2h."

  depends_on = [google_project_service.iam]
}

# ─────────────────────────────────────────────────────────────────────
# Cloud SQL access
# ─────────────────────────────────────────────────────────────────────

# Cloud SQL Auth Proxy 経由で接続するためのロール
resource "google_project_iam_member" "etl_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.etl.email}"
}

# ─────────────────────────────────────────────────────────────────────
# Vertex AI (text-embedding-004)
# ─────────────────────────────────────────────────────────────────────

resource "google_project_iam_member" "etl_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.etl.email}"

  depends_on = [google_project_service.aiplatform]
}

# ─────────────────────────────────────────────────────────────────────
# Logging (Cloud Logging に書き込めるようにする)
# ─────────────────────────────────────────────────────────────────────

resource "google_project_iam_member" "etl_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.etl.email}"
}

# ─────────────────────────────────────────────────────────────────────
# Scheduler Service Account (step 3)
# ─────────────────────────────────────────────────────────────────────
# Cloud Scheduler は専用 SA で Cloud Run Job を invoke する。
# (Cloud Scheduler の default SA を使う方法もあるが、IAM 権限を明示するため分離)

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = local.sa_scheduler_id
  display_name = "fujisawa-platform Cloud Scheduler invoker"
  description  = "Cloud Scheduler が Cloud Run Job を起動するための SA. Phase 4-2h step 3."

  depends_on = [google_project_service.iam]
}
