################################################################################
# Secret Manager — Cloud Run service が env としてマウントする秘匿情報。
#
# 1. piyolog-line-channel-secret        LINE Messaging API channel secret
# 2. piyolog-line-channel-access-token  LINE Messaging API access token
# 3. piyolog-database-url               SQLAlchemy URL (Cloud SQL connector socket 経由)
#
# DB URL は TF が組み立てて初期 version まで投入する (Cloud SQL のパスワードを TF が
# 知っているため)。LINE 関連は LINE Developers Console から取得する必要があるので、
# default は空 secret container のみ作成 (`create_line_secret_versions=false`)。
# 取得後 `gcloud secrets versions add ... --data-file=-` で投入する手順。
################################################################################

resource "google_secret_manager_secret" "line_channel_secret" {
  project   = var.project_id
  secret_id = local.secret_line_channel_secret

  replication {
    auto {}
  }

  labels = {
    component = "piyolog-analytics"
    purpose   = "line-channel-secret"
  }
}

resource "google_secret_manager_secret" "line_channel_access_token" {
  project   = var.project_id
  secret_id = local.secret_line_channel_access_token

  replication {
    auto {}
  }

  labels = {
    component = "piyolog-analytics"
    purpose   = "line-channel-access-token"
  }
}

resource "google_secret_manager_secret" "database_url" {
  project   = var.project_id
  secret_id = local.secret_database_url

  replication {
    auto {}
  }

  labels = {
    component = "piyolog-analytics"
    purpose   = "database-url"
  }
}

# --- 初期 version 投入 ---

# DATABASE_URL は TF が組み立て可能なので、毎 apply で最新 version に更新する。
resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.database_url.id
  secret_data = local.database_url
}

# LINE secrets は基本的に手動投入だが、`create_line_secret_versions=true` のときだけ
# tfvars 経由で値を入れる (state 漏洩リスクと引き換えのお手軽 path)。
resource "google_secret_manager_secret_version" "line_channel_secret" {
  count       = var.create_line_secret_versions ? 1 : 0
  secret      = google_secret_manager_secret.line_channel_secret.id
  secret_data = var.line_channel_secret_value
}

resource "google_secret_manager_secret_version" "line_channel_access_token" {
  count       = var.create_line_secret_versions ? 1 : 0
  secret      = google_secret_manager_secret.line_channel_access_token.id
  secret_data = var.line_channel_access_token_value
}
