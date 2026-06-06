################################################################################
# Pub/Sub ingestion (PROPOSAL-0010 / Phase 5 案E-1)
#
# イベント入口を Pub/Sub にし、Cloud Storage サブスクリプションで既存 raw バケットへ
# 流し込む。出口の BigQuery external table / dbt は流用 (bigquery.tf)。
#
#   AnalyticsLogger.emit → PubSubSink.publish → topic(events)
#       → Cloud Storage サブスク (text=NDJSON) → gs://<raw>/<events_prefix>/...
#       → BigQuery external table → dbt
#   恒久失敗 → dead-letter topic (+ 保持用 pull サブスク)
#
# enable_pubsub=false で全リソースを作らない (段階適用用)。
################################################################################

locals {
  pubsub_count = var.enable_pubsub ? 1 : 0

  events_topic_name     = "${var.name_prefix}-events"
  events_dlq_topic_name = "${var.name_prefix}-events-dlq"
  events_gcs_sub_name   = "${var.name_prefix}-events-to-gcs"
  events_dlq_sub_name   = "${var.name_prefix}-events-dlq-sub"

  # Pub/Sub サービスエージェント (Cloud Storage サブスクの GCS 書込 / dead-letter 転送に使う)。
  pubsub_sa_email = var.enable_pubsub ? google_project_service_identity.pubsub[0].email : null
}

# Pub/Sub サービスエージェントを明示プロビジョニング (email を確実に取得するため)。
resource "google_project_service_identity" "pubsub" {
  count    = local.pubsub_count
  provider = google-beta
  project  = var.project_id
  service  = "pubsub.googleapis.com"
}

# --- Topics ----------------------------------------------------------------

resource "google_pubsub_topic" "events" {
  count   = local.pubsub_count
  project = var.project_id
  name    = local.events_topic_name

  message_retention_duration = var.pubsub_topic_retention_duration

  labels = {
    component = "analytics-platform"
    purpose   = "event-ingest"
  }
}

resource "google_pubsub_topic" "events_dlq" {
  count   = local.pubsub_count
  project = var.project_id
  name    = local.events_dlq_topic_name

  labels = {
    component = "analytics-platform"
    purpose   = "event-dead-letter"
  }
}

# --- Cloud Storage サブスク (events → raw bucket、text=NDJSON) ----------------

resource "google_pubsub_subscription" "events_to_gcs" {
  count   = local.pubsub_count
  project = var.project_id
  name    = local.events_gcs_sub_name
  topic   = google_pubsub_topic.events[0].id

  cloud_storage_config {
    bucket          = google_storage_bucket.raw.name
    filename_prefix = "${var.gcs_events_prefix}/"
    filename_suffix = ".json"
    max_duration    = var.pubsub_gcs_max_duration
    max_bytes       = var.pubsub_gcs_max_bytes
    # avro_config を指定しない = text 出力 (message body をそのまま改行区切り = NDJSON)。
  }

  # 恒久失敗は dead-letter topic へ。
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.events_dlq[0].id
    max_delivery_attempts = var.dead_letter_max_delivery_attempts
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  # サブスク作成時点で Pub/Sub SA に GCS 書込権限が要る。
  depends_on = [
    google_storage_bucket_iam_member.pubsub_raw_creator,
    google_storage_bucket_iam_member.pubsub_raw_reader,
  ]
}

# dead-letter を保持・確認するための pull サブスク (無いと DLQ メッセージは期限切れで消える)。
resource "google_pubsub_subscription" "events_dlq" {
  count   = local.pubsub_count
  project = var.project_id
  name    = local.events_dlq_sub_name
  topic   = google_pubsub_topic.events_dlq[0].id

  message_retention_duration = var.pubsub_message_retention_duration
  retain_acked_messages      = false
  expiration_policy {
    ttl = "" # 失効させない
  }
}

# --- IAM -------------------------------------------------------------------

# (1) Cloud Storage サブスクが raw バケットへ書くための Pub/Sub SA 権限。
#     公式要件: objectCreator + legacyBucketReader。
resource "google_storage_bucket_iam_member" "pubsub_raw_creator" {
  count  = local.pubsub_count
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${local.pubsub_sa_email}"
}

resource "google_storage_bucket_iam_member" "pubsub_raw_reader" {
  count  = local.pubsub_count
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.legacyBucketReader"
  member = "serviceAccount:${local.pubsub_sa_email}"
}

# (2) dead-letter 転送のための Pub/Sub SA 権限 (publisher on DLQ + subscriber on sub)。
resource "google_pubsub_topic_iam_member" "pubsub_dlq_publisher" {
  count   = local.pubsub_count
  project = var.project_id
  topic   = google_pubsub_topic.events_dlq[0].name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${local.pubsub_sa_email}"
}

resource "google_pubsub_subscription_iam_member" "pubsub_events_subscriber" {
  count        = local.pubsub_count
  project      = var.project_id
  subscription = google_pubsub_subscription.events_to_gcs[0].name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${local.pubsub_sa_email}"
}

# (3) consumer エージェントの SA に topic への publish 権限を付与。
#     SA email は各 consumer module 配備後に var で渡す (既定 [] = まだ付与しない)。
resource "google_pubsub_topic_iam_member" "publishers" {
  for_each = var.enable_pubsub ? toset(var.publisher_service_account_emails) : toset([])
  project  = var.project_id
  topic    = google_pubsub_topic.events[0].name
  role     = "roles/pubsub.publisher"
  member   = "serviceAccount:${each.value}"
}
