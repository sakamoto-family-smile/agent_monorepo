# media (チャート画像 / 全文 Markdown) 配信用 GCS バケット (PROPOSAL-0011 P3-A)。
#
# worker が分析結果のチャート/全文をアップロードし、その V4 署名付き URL を LINE に渡す。
# worker が複数 instance に増えてもインメモリと違い 404 にならない。
#
# 公開設定:
# - バケットは非公開 (allUsers なし)。LINE / 本人は署名付き URL (既定 24 時間で失効) で
#   のみ取得できる。オブジェクト名も推測不可なランダム ID。
# - lifecycle で 1 日後に自動削除 (一時配信のみ、保存目的ではない)。

resource "google_storage_bucket" "media" {
  project                     = var.project_id
  name                        = local.media_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
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

# Cloud Run (webhook + worker は同一 runtime SA) が media をアップロードできる。
resource "google_storage_bucket_iam_member" "media_writer" {
  bucket = google_storage_bucket.media.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.service.email}"
}

# 署名付き URL の生成: runtime SA は秘密鍵を持たないため IAM signBlob で署名する。
# そのため runtime SA 自身に対して Token Creator (iam.serviceAccounts.signBlob) を付与する。
resource "google_service_account_iam_member" "service_self_sign_blob" {
  service_account_id = google_service_account.service.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.service.email}"
}
