################################################################################
# Step 9: Cloud Monitoring アラート
#
# 検知対象 (重要度の高いものから):
#   1. Cloud Workflows の execution が FAILED で終わった
#   2. Cloud Run Job (analytics-platform-dbt) の execution が failed
#   3. Cloud Run Job の duration が想定より長い (タイムアウト前兆)
#
# 通知:
#   - email チャンネル (var.notification_email、空文字なら作らない)
#   - Slack はネイティブ統合に Slack OAuth が必要なので、Workflow 側 (Step 8) の
#     in-workflow Slack webhook と併用する想定。Pub/Sub 経由で Slack に飛ばすなら
#     google_monitoring_notification_channel(type="pubsub") を別途追加する。
#
# enable_alerts = false で全部スキップ可能 (sandbox / dev で API 課金を抑える)。
################################################################################

locals {
  alerts_enabled        = var.enable_alerts
  email_channel_enabled = local.alerts_enabled && var.notification_email != ""
}

# --- Notification channel (email) ----------------------------------------

resource "google_monitoring_notification_channel" "email" {
  count = local.email_channel_enabled ? 1 : 0

  project      = var.project_id
  display_name = "analytics-platform alerts (email)"
  type         = "email"
  description  = "Receives alert pages for analytics-platform Phase 5 pipeline."

  labels = {
    email_address = var.notification_email
  }

  # 通知が抑制されないように force_delete = false (default) のまま
}

# --- Helper: 共通の notification_channels list ---------------------------

locals {
  notification_channels = local.email_channel_enabled ? [
    google_monitoring_notification_channel.email[0].name,
  ] : []
}

# --- Alert 1: Cloud Workflows execution FAILED ---------------------------
#
# metric: workflowexecutions.googleapis.com/finished_execution_count
# label : status="FAILED"
# 5 分間に 1 件でも FAILED があったら page

resource "google_monitoring_alert_policy" "workflow_failed" {
  count = local.alerts_enabled ? 1 : 0

  project      = var.project_id
  display_name = "analytics-platform: Cloud Workflows execution FAILED"
  combiner     = "OR"

  documentation {
    content   = <<-EOT
      Cloud Workflows ${local.workflow_name_for_filter} の execution が FAILED で終了した。

      確認手順:
      1. Cloud Logging で resource.type=workflows.googleapis.com/Workflow を絞り込む
      2. severity=ERROR の log を確認 (どのステップで失敗したか)
      3. Workflow が呼ぶ Cloud Run Job (${var.cloud_run_job_name_for_filter}) の execution を確認
      4. dbt の compile / run / test エラーかどうか切り分け
    EOT
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "Workflow FAILED count > 0 over 5m"

    condition_threshold {
      filter          = <<-EOT
        metric.type="workflowexecutions.googleapis.com/finished_execution_count"
        resource.type="workflows.googleapis.com/Workflow"
        metric.label.status="FAILED"
      EOT
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "300s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels

  alert_strategy {
    auto_close = "1800s" # 30 分間 healthy なら自動クローズ
  }

  user_labels = {
    component = "analytics-platform"
    severity  = "high"
    step      = "9"
  }
}

# --- Alert 2: Cloud Run Job (analytics-platform-dbt) failed --------------
#
# metric: run.googleapis.com/job/completed_execution_count (label result=failed)

resource "google_monitoring_alert_policy" "dbt_job_failed" {
  count = local.alerts_enabled ? 1 : 0

  project      = var.project_id
  display_name = "analytics-platform: dbt Cloud Run Job execution failed"
  combiner     = "OR"

  documentation {
    content   = <<-EOT
      Cloud Run Job ${var.cloud_run_job_name_for_filter} の execution が failed で完了。
      Workflow alert より早く検知できることが多い (Workflow は retry 後に FAILED 確定)。

      確認手順:
      1. Cloud Run コンソールで Job のログを確認
      2. dbt run / dbt test のエラーか、認証/Workload Identity か切り分け
      3. BigQuery jobs.list で関連クエリのエラーを確認
    EOT
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "dbt Job failed count > 0 over 5m"

    condition_threshold {
      filter          = <<-EOT
        metric.type="run.googleapis.com/job/completed_execution_count"
        resource.type="cloud_run_job"
        resource.label.job_name="${var.cloud_run_job_name_for_filter}"
        metric.label.result="failed"
      EOT
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "300s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels

  alert_strategy {
    auto_close = "1800s"
  }

  user_labels = {
    component = "analytics-platform"
    severity  = "high"
    step      = "9"
  }
}

# --- Alert 3: Cloud Run Job duration が長い (タイムアウト前兆) -----------
#
# metric: run.googleapis.com/job/execution/duration_ms (max を見る)
# しきい値: var.dbt_job_max_duration_seconds (default 30 分)

resource "google_monitoring_alert_policy" "dbt_job_slow" {
  count = local.alerts_enabled && var.dbt_job_max_duration_seconds > 0 ? 1 : 0

  project      = var.project_id
  display_name = "analytics-platform: dbt Cloud Run Job duration too long"
  combiner     = "OR"

  documentation {
    content   = <<-EOT
      Cloud Run Job ${var.cloud_run_job_name_for_filter} の execution duration が
      ${var.dbt_job_max_duration_seconds} 秒を超えた。

      考えられる原因:
      - BigQuery クエリのスキャン量が想定より大きい (パーティションプルーニング失敗)
      - external table が 大量の小ファイルを参照していて metadata 読込が重い
      - dbt の依存グラフに循環や重複がある
    EOT
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "dbt Job duration p95 > threshold"

    condition_threshold {
      filter = <<-EOT
        metric.type="run.googleapis.com/job/execution/duration_ms"
        resource.type="cloud_run_job"
        resource.label.job_name="${var.cloud_run_job_name_for_filter}"
      EOT
      # ms で来るので閾値も ms 換算
      comparison      = "COMPARISON_GT"
      threshold_value = var.dbt_job_max_duration_seconds * 1000
      duration        = "60s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MAX"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels

  alert_strategy {
    auto_close = "3600s"
  }

  user_labels = {
    component = "analytics-platform"
    severity  = "medium"
    step      = "9"
  }
}

# --- Helper local for documentation strings -----------------------------

locals {
  # Workflow 名は Step 8 の deploy_orchestration.sh と合わせる必要がある。
  # var で上書き可能 (default: analytics-platform-dbt-pipeline)。
  workflow_name_for_filter = var.workflow_name_for_filter
}
