locals {
  labels = {
    project = "stock-analysis-agent"
    managed = "terraform"
  }

  # 命名規約
  sa_service_name        = "sa-${var.service_name}"
  artifact_registry_repo = var.service_name

  # PROPOSAL-0011 P3-A: Cloud Tasks worker + media bucket + invoker SA
  sa_tasks_invoker_name = "sa-stock-tasks-invoker"
  media_bucket_name     = "${var.service_name}-media"
  tasks_worker_endpoint = local.deploy_worker ? "${google_cloud_run_v2_service.worker[0].uri}/api/tasks/analyze" : ""
  deploy_worker         = length(trimspace(var.image)) > 0

  # Secret 名 (Cloud Run Service が secret_key_ref で参照)。値は手動投入。
  secret_line_channel_secret       = "${var.service_name}-line-channel-secret"
  secret_line_channel_access_token = "${var.service_name}-line-channel-access-token"
  secret_claude_code_oauth_token   = "${var.service_name}-claude-code-oauth-token"
  secret_brave_api_key             = "${var.service_name}-brave-api-key"
  secret_db_password               = "${var.service_name}-db-password"

  # image 指定があるときだけ Cloud Run Service を作る (chicken-and-egg 回避)
  deploy_service = length(trimspace(var.image)) > 0
}
