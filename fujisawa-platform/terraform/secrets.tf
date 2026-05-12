# Phase 4-2h step 2: Secret Manager。
#
# 設計方針 (proposal §4.5):
# - 機密情報 (DB password / User-Agent / Vertex project_id) は Secret Manager で管理
# - DB password は cloudsql.tf の random_password で生成し自動投入
# - User-Agent と Vertex project_id は手動投入 (`gcloud secrets versions add`、SETUP.md §5)
# - Cloud Run Job が `latest` バージョンを env 経由で読む (step 3 で配線)

# ─────────────────────────────────────────────────────────────────────
# DB password (cloudsql.tf で自動投入)
# ─────────────────────────────────────────────────────────────────────

resource "google_secret_manager_secret" "db_password" {
  project   = var.project_id
  secret_id = local.secret_db_password

  replication {
    auto {}
  }

  labels = local.labels

  depends_on = [google_project_service.secretmanager]
}

# ─────────────────────────────────────────────────────────────────────
# User-Agent (手動投入。連絡先 URL 必須、PoliteFetcher の礼儀)
# ─────────────────────────────────────────────────────────────────────

resource "google_secret_manager_secret" "user_agent" {
  project   = var.project_id
  secret_id = local.secret_user_agent

  replication {
    auto {}
  }

  labels = local.labels

  depends_on = [google_project_service.secretmanager]
}

# ─────────────────────────────────────────────────────────────────────
# Vertex project id (手動投入。Cloud Run Job が VertexEmbeddingClient 構築時に参照)
# ─────────────────────────────────────────────────────────────────────

resource "google_secret_manager_secret" "vertex_project" {
  project   = var.project_id
  secret_id = local.secret_vertex_project

  replication {
    auto {}
  }

  labels = local.labels

  depends_on = [google_project_service.secretmanager]
}

# ─────────────────────────────────────────────────────────────────────
# IAM: ETL SA に Secret Accessor 権限
# ─────────────────────────────────────────────────────────────────────

resource "google_secret_manager_secret_iam_member" "etl_db_password" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.db_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.etl.email}"
}

resource "google_secret_manager_secret_iam_member" "etl_user_agent" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.user_agent.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.etl.email}"
}

resource "google_secret_manager_secret_iam_member" "etl_vertex_project" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.vertex_project.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.etl.email}"
}
