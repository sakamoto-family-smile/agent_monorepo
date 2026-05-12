locals {
  # ─── Labels (全リソース共通) ───────────────────────────────────────
  labels = {
    project    = "fujisawa-platform"
    managed_by = "terraform"
  }

  # ─── Cloud SQL ─────────────────────────────────────────────────────
  cloudsql_database_name = "fujisawa_kb_db"
  cloudsql_etl_user_name = "${var.name_prefix}_etl_user"

  # ─── Service Account ───────────────────────────────────────────────
  sa_etl_id    = "sa-fujisawa-etl"
  sa_etl_email = google_service_account.etl.email

  # ─── Secret Manager (値は手動投入。terraform は枠のみ) ───────────
  secret_db_password    = "${var.name_prefix}-etl-db-password"
  secret_user_agent     = "${var.name_prefix}-etl-user-agent"
  secret_vertex_project = "${var.name_prefix}-etl-vertex-project"

  # ─── GCS bucket (PdfArchive) ───────────────────────────────────────
  pdf_archive_bucket_name = "${var.name_prefix}-pdf-archive-${var.project_id}"

  # ─── Artifact Registry ─────────────────────────────────────────────
  artifact_registry_repo_id = "${var.name_prefix}-etl"
}
