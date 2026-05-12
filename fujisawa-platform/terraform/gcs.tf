# Phase 4-2h step 2: PdfArchive 用 GCS bucket。
#
# 設計方針 (proposal §4.5 line 204 / Phase 4-2c-2):
# - 全 ETL Job (biyearly_admission / monthly_vacancy / yearly_navi / wayback_backfill) が
#   fetch した PDF を一次保存する
# - bucket 名は project ID で衝突回避 (GCS bucket 名はグローバル一意)
# - lifecycle で古い PDF を自動削除 (default 3 年、コスト最適化)
# - SOFT_DELETE / versioning は無効 (PDF は決定的 path で同じバイトを書くため不要)

resource "google_storage_bucket" "pdf_archive" {
  project       = var.project_id
  name          = local.pdf_archive_bucket_name
  location      = var.pdf_archive_bucket_location
  storage_class = "STANDARD"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  labels = local.labels

  versioning {
    enabled = false
  }

  dynamic "lifecycle_rule" {
    for_each = var.pdf_archive_bucket_lifecycle_age_days > 0 ? [1] : []
    content {
      condition {
        age = var.pdf_archive_bucket_lifecycle_age_days
      }
      action {
        type = "Delete"
      }
    }
  }

  depends_on = [google_project_service.storage]
}

# ETL SA に bucket への object admin 権限を付与
resource "google_storage_bucket_iam_member" "etl_pdf_archive_admin" {
  bucket = google_storage_bucket.pdf_archive.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.etl.email}"
}

# consumer (info-bot / 保活) に object viewer 権限を付与 (空 list なら no-op)
resource "google_storage_bucket_iam_member" "consumer_pdf_archive_viewer" {
  for_each = toset(var.consumer_service_account_emails)

  bucket = google_storage_bucket.pdf_archive.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${each.value}"
}
