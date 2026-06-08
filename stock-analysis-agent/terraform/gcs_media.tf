# media (チャート画像 / 全文 Markdown) 配信用 GCS バケット (PROPOSAL-0011 P3-A)。
#
# worker が分析結果のチャート/全文をアップロードし、その公開 URL を LINE に渡す。
# worker が複数 instance に増えてもインメモリと違い 404 にならない。
#
# 公開設定:
# - LINE (匿名) が取得するため allUsers に objectViewer ではなく legacyObjectReader
#   (= get のみ、list 不可) を付与。オブジェクト名は推測不可なランダム ID。
# - lifecycle で 1 日後に自動削除 (一時配信のみ、保存目的ではない)。

resource "google_storage_bucket" "media" {
  project                     = var.project_id
  name                        = local.media_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true
  labels                      = local.labels

  lifecycle_rule {
    condition {
      age = var.media_retention_days
    }
    action {
      type = "Delete"
    }
  }
}

# LINE が画像/全文を取得できるよう、オブジェクト read のみ public に開ける。
resource "google_storage_bucket_iam_member" "media_public_read" {
  bucket = google_storage_bucket.media.name
  role   = "roles/storage.legacyObjectReader"
  member = "allUsers"
}

# Cloud Run (webhook + worker は同一 runtime SA) が media をアップロードできる。
resource "google_storage_bucket_iam_member" "media_writer" {
  bucket = google_storage_bucket.media.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.service.email}"
}
