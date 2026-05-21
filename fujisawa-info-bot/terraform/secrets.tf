# Secret Manager: LINE Channel 認証 + Cloud SQL consumer user password。
#
# terraform は **secret resource** だけ作成し、 値 (version) は別経路で投入する。
# LINE 値は LINE Developers Console で Channel を作ってから取得 →
#   `gcloud secrets versions add ... --data-file=-` で投入。
# DB password は本ファイル下部で random_password を生成して自動投入。

resource "google_secret_manager_secret" "line_channel_secret" {
  secret_id = local.secret_line_channel_secret
  replication {
    auto {}
  }
  labels = local.labels

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret" "line_channel_access_token" {
  secret_id = local.secret_line_channel_access_token
  replication {
    auto {}
  }
  labels = local.labels

  depends_on = [google_project_service.secretmanager]
}

# Cloud SQL consumer user の password (terraform 自動生成 → secret manager 投入)
resource "random_password" "kb_db_consumer" {
  length  = 32
  special = true
  # PostgreSQL の標準的な special 集合に限定 (URL-encode 不要にする)
  override_special = "!@#$%^&*()-_=+[]{}<>"
}

resource "google_secret_manager_secret" "kb_db_password" {
  secret_id = local.secret_kb_db_password
  replication {
    auto {}
  }
  labels = local.labels

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret_version" "kb_db_password" {
  secret      = google_secret_manager_secret.kb_db_password.id
  secret_data = random_password.kb_db_consumer.result
}

# Service Account に各 Secret への accessor 権限を付与
resource "google_secret_manager_secret_iam_member" "service_line_channel_secret" {
  secret_id = google_secret_manager_secret.line_channel_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.service.email}"
}

resource "google_secret_manager_secret_iam_member" "service_line_channel_access_token" {
  secret_id = google_secret_manager_secret.line_channel_access_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.service.email}"
}

resource "google_secret_manager_secret_iam_member" "service_kb_db_password" {
  secret_id = google_secret_manager_secret.kb_db_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.service.email}"
}
