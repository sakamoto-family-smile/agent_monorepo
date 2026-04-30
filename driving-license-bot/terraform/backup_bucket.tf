# Phase 2-Y1: Firestore + Cloud SQL のバックアップ保存先 GCS bucket。
#
# teardown-app の前に backup_data.sh で以下を export:
#   - Firestore: gs://<bucket>/firestore/<TS>/
#   - Cloud SQL: gs://<bucket>/cloudsql/<TS>/dump.sql
#   - LATEST pointer: gs://<bucket>/LATEST  (中身に最新 TS)
#
# 再 apply 後に restore_data.sh で LATEST を読んで自動復元する。
#
# 設計判断:
# - bucket は teardown-app では削除しない（backup を保護）。force_destroy=false +
#   オブジェクトが残っていれば terraform destroy で失敗する自然な防御。
# - 完全削除したい場合は backup_bucket_force_destroy=true で再 apply → destroy。
# - versioning ON で誤削除に備える。lifecycle 30 日で古い archive を整理。
# - Firestore export 用 service agent と Cloud SQL service account に
#   bucket への objectAdmin を TF で付与（手動操作不要）。

resource "google_storage_bucket" "backups" {
  project       = var.project_id
  name          = "${var.project_id}-${var.name_prefix}-backups"
  location      = var.region
  storage_class = "STANDARD"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  force_destroy = var.backup_bucket_force_destroy

  versioning {
    enabled = true
  }

  # current version を 90 日経過で削除（明示 TTL なら早めに）
  lifecycle_rule {
    condition {
      age        = var.backup_retention_days
      with_state = "LIVE"
    }
    action {
      type = "Delete"
    }
  }

  # noncurrent (上書きされた古い世代) は短く 14 日で消す
  lifecycle_rule {
    condition {
      age                = 14
      with_state         = "ARCHIVED"
      num_newer_versions = 3
    }
    action {
      type = "Delete"
    }
  }

  labels = local.labels

  depends_on = [google_project_service.firestore]
}

# Firestore service agent (export/import を実行する Google-managed SA)
# Format: service-<PROJECT_NUMBER>@gcp-sa-firestore.iam.gserviceaccount.com
# 初回 Firestore 操作時に自動作成されるので depends_on で firestore database を待つ
resource "google_storage_bucket_iam_member" "firestore_export_writer" {
  bucket = google_storage_bucket.backups.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-firestore.iam.gserviceaccount.com"

  depends_on = [google_firestore_database.default]
}

# Cloud SQL instance service account (export/import を実行)
resource "google_storage_bucket_iam_member" "cloudsql_export_writer" {
  bucket = google_storage_bucket.backups.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_sql_database_instance.main.service_account_email_address}"
}
