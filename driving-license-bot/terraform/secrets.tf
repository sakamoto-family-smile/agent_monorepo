# Secret Manager の secret 「枠」のみ Terraform 管理。
# 値の投入は手動（`gcloud secrets versions add` または Console）。
# Terraform に値を持ち込まない理由:
#   - tfstate に平文で残る
#   - Phase ごとに rotation 管理を分離

resource "google_secret_manager_secret" "line_channel_secret" {
  project   = var.project_id
  secret_id = local.secret_line_channel_secret

  replication {
    auto {}
  }

  labels = local.labels

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret" "line_channel_access_token" {
  project   = var.project_id
  secret_id = local.secret_line_channel_access_token

  replication {
    auto {}
  }

  labels = local.labels

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret" "line_login_channel_secret" {
  project   = var.project_id
  secret_id = local.secret_line_login_channel_secret

  replication {
    auto {}
  }

  labels = local.labels

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret" "operator_user_ids" {
  project   = var.project_id
  secret_id = local.secret_operator_user_ids

  replication {
    auto {}
  }

  labels = local.labels

  depends_on = [google_project_service.secretmanager]
}

# ---- IAM: sa-line-bot に accessor 権限 ----

resource "google_secret_manager_secret_iam_member" "line_bot_channel_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.line_channel_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.sa_line_bot_email}"
}

resource "google_secret_manager_secret_iam_member" "line_bot_channel_access_token" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.line_channel_access_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.sa_line_bot_email}"
}

resource "google_secret_manager_secret_iam_member" "line_bot_operator_user_ids" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.operator_user_ids.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.sa_line_bot_email}"
}
