locals {
  # Service names
  line_bot_service_name = "${var.name_prefix}-line-bot"

  # Service Account ID（小文字 + 数字 + ハイフン、6-30 chars）
  sa_line_bot_id = "sa-line-bot"

  sa_line_bot_email = google_service_account.line_bot.email

  # Phase 2-A3: バッチ生成 pipeline 用の SA（deploy_batch.sh と命名揃え）
  sa_batch_id     = "sa-batch"
  sa_workflow_id  = "sa-workflow"
  sa_scheduler_id = "sa-scheduler"

  sa_batch_email     = google_service_account.batch.email
  sa_workflow_email  = google_service_account.workflow.email
  sa_scheduler_email = google_service_account.scheduler.email

  # Secret Manager の secret 名（LINE 系は値を手動投入、cloudsql は random_password）
  secret_line_channel_secret       = "${var.name_prefix}-line-channel-secret"
  secret_line_channel_access_token = "${var.name_prefix}-line-channel-access-token"
  secret_line_login_channel_secret = "${var.name_prefix}-line-login-channel-secret"
  secret_operator_user_ids         = "${var.name_prefix}-operator-line-user-ids"
  # Phase 2-A1: Cloud SQL `app` user password。Terraform が random_password で生成し
  # Secret Manager に格納する。tfstate に値が残る点は PoC として容認（バケットは private）。
  secret_cloudsql_password = "${var.name_prefix}-cloudsql-password"

  # Phase 2-A1: Cloud SQL instance 名と DB / user 名
  cloudsql_instance_name = "${var.name_prefix}-pg"
  cloudsql_database_name = "question_bank"
  cloudsql_user_name     = "app"

  # Common labels
  labels = {
    project     = var.name_prefix
    managed_by  = "terraform"
    environment = "dev"
  }
}
