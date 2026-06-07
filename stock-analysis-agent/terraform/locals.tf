locals {
  labels = {
    project = "stock-analysis-agent"
    managed = "terraform"
  }

  # 命名規約
  sa_service_name        = "sa-${var.service_name}"
  artifact_registry_repo = var.service_name

  # Secret 名 (Cloud Run Service が secret_key_ref で参照)。値は手動投入。
  secret_line_channel_secret       = "${var.service_name}-line-channel-secret"
  secret_line_channel_access_token = "${var.service_name}-line-channel-access-token"
  secret_claude_code_oauth_token   = "${var.service_name}-claude-code-oauth-token"
  secret_brave_api_key             = "${var.service_name}-brave-api-key"

  # image 指定があるときだけ Cloud Run Service を作る (chicken-and-egg 回避)
  deploy_service = length(trimspace(var.image)) > 0
}
