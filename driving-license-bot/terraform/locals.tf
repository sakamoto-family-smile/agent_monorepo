locals {
  # Service names
  line_bot_service_name = "${var.name_prefix}-line-bot"

  # Service Account ID（小文字 + 数字 + ハイフン、6-30 chars）
  sa_line_bot_id = "sa-line-bot"

  sa_line_bot_email = google_service_account.line_bot.email

  # Secret Manager の secret 名（値は手動投入）
  secret_line_channel_secret       = "${var.name_prefix}-line-channel-secret"
  secret_line_channel_access_token = "${var.name_prefix}-line-channel-access-token"
  secret_line_login_channel_secret = "${var.name_prefix}-line-login-channel-secret"
  secret_operator_user_ids         = "${var.name_prefix}-operator-line-user-ids"

  # Common labels
  labels = {
    project     = var.name_prefix
    managed_by  = "terraform"
    environment = "dev"
  }
}
