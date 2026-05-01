# Phase 2-B3: バッチ運用 hardening — Cloud Monitoring alert + 通知チャネル。
#
# 設計判断:
# - LINE Push (運営者通知) はアプリ層 (operator_notify.py) で実装。Push クォータ消費
#   を抑えるため pool_low_alert 検知時のみ送る。
# - 重複した警報経路として Cloud Monitoring alert を email で送る (channel: email)。
#   - Cloud Run Job (driving-license-bot-batch) の失敗 → 即時通知
#   - log-based metric `business_event/pool_low_alert` のカウント → 5 分以内に 1+ で発火
# - alert_notification_emails が空なら全リソース skip (個人運用初期は LINE Push のみで OK)。

locals {
  deploy_alert = length(var.alert_notification_emails) > 0
}

# ---- 通知チャネル (email) ----

resource "google_monitoring_notification_channel" "operator_email" {
  for_each = local.deploy_alert ? toset(var.alert_notification_emails) : toset([])

  project      = var.project_id
  display_name = "driving-license-bot operator (${each.value})"
  type         = "email"
  labels = {
    email_address = each.value
  }

  user_labels = local.labels

  depends_on = [google_project_service.monitoring]
}

# ---- log-based metric: business_event=pool_low_alert ----
# emit_business_event(action="pool_low_alert") の発火回数を集計。
# Cloud Logging に流れる JSON payload の `action` フィールドを抽出する。

resource "google_logging_metric" "pool_low_alert_count" {
  count = local.deploy_alert ? 1 : 0

  project = var.project_id
  name    = "${var.name_prefix}-pool-low-alert-count"

  filter = <<-EOT
    resource.type="cloud_run_job"
    resource.labels.job_name="${local.batch_job_name}"
    jsonPayload.event_type="business_event"
    jsonPayload.action="pool_low_alert"
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }

  depends_on = [google_project_service.monitoring]
}

# ---- alert policy 1: pool_low_alert の発火検知 ----

resource "google_monitoring_alert_policy" "pool_low_alert" {
  count = local.deploy_alert ? 1 : 0

  project      = var.project_id
  display_name = "driving-license-bot pool_low_alert"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "pool_low_alert occurred"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.pool_low_alert_count[0].name}\" resource.type=\"cloud_run_job\""
      duration        = "0s"
      comparison      = "COMPARISON_GT"
      threshold_value = var.pool_low_alert_threshold - 1

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  notification_channels = [
    for ch in google_monitoring_notification_channel.operator_email : ch.id
  ]

  documentation {
    content = "driving-license-bot のバッチ完了時にプール枯渇 (pool_count < threshold) を検知。`make batch-trigger` で問題を補充するか、生成 LLM の応答品質を確認。"
  }

  user_labels = local.labels

  depends_on = [google_project_service.monitoring]
}

# ---- alert policy 2: Cloud Run Job execution 失敗 ----

resource "google_monitoring_alert_policy" "batch_job_failure" {
  count = local.deploy_alert ? 1 : 0

  project      = var.project_id
  display_name = "driving-license-bot batch job failure"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "batch execution failed"

    condition_threshold {
      filter          = "metric.type=\"run.googleapis.com/job/completed_execution_count\" resource.type=\"cloud_run_job\" resource.label.\"job_name\"=\"${local.batch_job_name}\" metric.label.\"result\"=\"failed\""
      duration        = "0s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  notification_channels = [
    for ch in google_monitoring_notification_channel.operator_email : ch.id
  ]

  documentation {
    content = "driving-license-bot の Cloud Run Job execution が失敗。Cloud Logging で `severity>=ERROR resource.labels.job_name=\"${local.batch_job_name}\"` を確認。"
  }

  user_labels = local.labels

  depends_on = [google_project_service.monitoring]
}
