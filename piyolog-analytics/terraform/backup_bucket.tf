################################################################################
# Phase 4-A: Cloud SQL バックアップ保存先 GCS bucket。
#
# `make tf-destroy` (Cloud SQL 含む) でデータ消失を避けるため、destroy 前に
# `make backup` で全テーブルを GCS に export する仕組み。再 apply 後に
# `make restore` で復元できる。
#
# 出力先:
#   gs://${PROJECT}-piyolog-backups/cloudsql/<TS>/dump.sql
#   gs://${PROJECT}-piyolog-backups/LATEST  (中身に最新 TS)
#
# 設計判断:
# - bucket は tf-destroy では削除しない (`force_destroy=false`)。backup を保護。
#   完全削除したい場合は `backup_bucket_force_destroy=true` で再 apply → destroy。
# - versioning ON で誤削除に備える。current 90 日 / archived 14 日で自動整理。
# - Cloud SQL service account に bucket への objectAdmin を TF で自動付与。
################################################################################

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

  # current version を `backup_retention_days` 経過で削除
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
}

# Cloud SQL instance service account に bucket への objectAdmin。
# export/import 時に Cloud SQL 側がこの SA で bucket を read/write する。
# 専用 / 共有モードのどちらでも、実際に使うインスタンスの SA を解決する
# (PROPOSAL-0009 P1)。
resource "google_storage_bucket_iam_member" "cloudsql_export_writer" {
  bucket = google_storage_bucket.backups.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${local.cloud_sql_service_account_email}"
}
