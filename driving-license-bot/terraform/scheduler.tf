# Phase 2-B2: Cloud Scheduler が定期的に Workflow を起動する。
#
# Workflow → Cloud Run Job という三段構成にすることで:
#   - Scheduler は Workflow の execution API を 1 回叩くだけ（HTTP target）
#   - Workflow が Cloud Run Job を起動 + retry / 結果ハンドリング
#   - Job 内で実際の生成 pipeline が回る
#
# Workflow をスキップして直接 Cloud Run Job を起動する選択肢もあるが、
# 失敗時の retry / 監視 / 引数受け渡しを宣言的に書ける Workflow を経由する
# (DESIGN.md §3.1.2)。

resource "google_cloud_scheduler_job" "batch_nightly" {
  count = local.deploy_batch ? 1 : 0

  project     = var.project_id
  region      = var.region
  name        = local.scheduler_job_name
  description = "Trigger driving-license-bot question generation workflow nightly."
  schedule    = var.batch_schedule_cron
  time_zone   = local.scheduler_time_zone

  attempt_deadline = "320s"

  retry_config {
    retry_count          = 1
    max_retry_duration   = "300s"
    min_backoff_duration = "10s"
    max_backoff_duration = "60s"
  }

  http_target {
    uri         = "https://workflowexecutions.googleapis.com/v1/projects/${var.project_id}/locations/${var.region}/workflows/${google_workflows_workflow.generation_pipeline[0].name}/executions"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode(jsonencode({
      argument = jsonencode({
        project    = var.project_id
        location   = var.region
        job_name   = local.batch_job_name
        total      = var.generation_batch_size
        difficulty = "standard"
      })
    }))

    oauth_token {
      service_account_email = local.sa_scheduler_email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [
    google_project_service.cloudscheduler,
    google_workflows_workflow.generation_pipeline,
    google_project_iam_member.scheduler_workflows_invoker,
  ]
}
