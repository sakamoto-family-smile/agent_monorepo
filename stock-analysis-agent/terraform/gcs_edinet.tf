# EDINET 用 GCS バケット (PROPOSAL-0011 P3-B)。
#
# 用途:
# - Edinetcode.csv (ticker→EDINET code 対応表) のホスト。worker/batch が
#   EDINET_CODE_CSV_PATH=gs://<bucket>/Edinetcode.csv で読む (手動アップロード)。
# - EDINET 書類本体 (PDF/XBRL) の cache (edinet-client GcsCache、prefix `edinet/`)。
#
# private バケット (公開不要)。Cloud Run 同一 runtime SA に objectAdmin を付与。

resource "google_storage_bucket" "edinet" {
  project                     = var.project_id
  name                        = local.edinet_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false
  labels                      = local.labels

  # cache は再取得可能なので一定期間で削除してコストを抑える。
  # Edinetcode.csv は prefix が異なる (edinet-code/) ため、cache prefix のみ対象。
  lifecycle_rule {
    condition {
      age            = var.edinet_cache_retention_days
      matches_prefix = ["edinet/"]
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket_iam_member" "edinet_writer" {
  bucket = google_storage_bucket.edinet.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.service.email}"
}
