# Secret Manager: LINE Channel 認証 + Claude OAuth token + Brave API key。
#
# terraform は **secret resource** だけ作成し、値 (version) は別経路で投入する:
#   - LINE 値:   LINE Developers Console で Channel 作成後に取得 →
#                `gcloud secrets versions add <name> --data-file=-`
#   - Claude:    `claude setup-token` で取得した OAuth token (有効期限 1 年)
#   - Brave:     brave.com の API key
#
# 値はリポジトリに置かない (手動投入)。SA には secret 単位で accessor を付与する。

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

resource "google_secret_manager_secret" "claude_code_oauth_token" {
  secret_id = local.secret_claude_code_oauth_token
  replication {
    auto {}
  }
  labels = local.labels

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret" "brave_api_key" {
  secret_id = local.secret_brave_api_key
  replication {
    auto {}
  }
  labels = local.labels

  depends_on = [google_project_service.secretmanager]
}

# DB password は terraform が生成して自動投入 (PROPOSAL-0011 P2-B)。
resource "google_secret_manager_secret" "db_password" {
  secret_id = local.secret_db_password
  replication {
    auto {}
  }
  labels = local.labels

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db_password.result
}

# SA に各 Secret への accessor 権限を付与
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

resource "google_secret_manager_secret_iam_member" "service_claude_code_oauth_token" {
  secret_id = google_secret_manager_secret.claude_code_oauth_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.service.email}"
}

resource "google_secret_manager_secret_iam_member" "service_brave_api_key" {
  secret_id = google_secret_manager_secret.brave_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.service.email}"
}

resource "google_secret_manager_secret_iam_member" "service_db_password" {
  secret_id = google_secret_manager_secret.db_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.service.email}"
}

# EDINET API key (PROPOSAL-0011 P3-B)。disclosure2.edinet-fsa.go.jp で無料登録した
# key を手動投入。EDINET 無効時は空文字 version で可 (collector が graceful skip)。
resource "google_secret_manager_secret" "edinet_api_key" {
  secret_id = local.secret_edinet_api_key
  replication {
    auto {}
  }
  labels = local.labels

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret_iam_member" "service_edinet_api_key" {
  secret_id = google_secret_manager_secret.edinet_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.service.email}"
}
