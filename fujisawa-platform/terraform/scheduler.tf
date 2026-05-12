# Phase 4-2h step 3: Cloud Scheduler × 6 (wayback_backfill 除く)。
#
# 設計判断 (proposal 0003 §4.5.4):
# - 定期 Job 6 個に Cloud Scheduler の cron trigger を付ける
# - wayback_backfill は **一度きり実行** なので Scheduler に登録しない (手動 invoke)
# - Scheduler は HTTP target で Cloud Run Jobs Admin API の `:run` を叩く
#   (Cloud Tasks 経由ではなく直接 invoke する単純構成)
# - 認証は OAuth token (sa-fujisawa-scheduler の SA でサインイン)
# - 各 Job は独立した Scheduler エントリ。共通テンプレートは for_each で生成

resource "google_cloud_scheduler_job" "etl" {
  for_each = local.deploy_jobs ? local.scheduled_jobs : {}

  project   = var.project_id
  region    = var.region
  name      = each.value.scheduler_name
  schedule  = each.value.cron
  time_zone = var.scheduler_time_zone

  description = "fujisawa-platform ${each.key} scheduler"

  retry_config {
    retry_count = 0 # Cloud Run Job 側の run_etl_job ラッパーで fail-fast 制御
  }

  http_target {
    http_method = "POST"
    uri = format(
      "https://%s-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/%s/jobs/%s:run",
      var.region,
      var.project_id,
      google_cloud_run_v2_job.etl[each.key].name,
    )

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [
    google_project_service.cloudscheduler,
    google_cloud_run_v2_job_iam_member.scheduler_invoker,
  ]
}
