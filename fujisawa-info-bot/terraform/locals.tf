locals {
  labels = {
    project = "fujisawa-info-bot"
    managed = "terraform"
  }

  # 命名規約
  sa_service_name        = "sa-${var.service_name}"
  sa_service_email       = "${local.sa_service_name}@${var.project_id}.iam.gserviceaccount.com"
  artifact_registry_repo = var.service_name

  # Secret 名 (Cloud Run Service が secret_key_ref で参照)
  secret_line_channel_secret       = "${var.service_name}-line-channel-secret"
  secret_line_channel_access_token = "${var.service_name}-line-channel-access-token"
  secret_kb_db_password            = "${var.service_name}-kb-db-password"

  # Cloud SQL DB user (info-bot 専用、 consumer_role 付与済を想定)
  cloudsql_consumer_user_name = "${replace(var.service_name, "-", "_")}_user"

  deploy_service = length(trimspace(var.image)) > 0
}
