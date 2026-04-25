################################################################################
# Step 4: BigQuery datasets + external table
#
# データセット 3 種:
#   - {bq_raw_dataset}      raw 層 (external table over GCS Hive)
#   - {bq_staging_dataset}  dbt staging
#   - {bq_marts_dataset}    dbt marts
#
# external table は raw bucket の `${gcs_raw_prefix}/` 配下を Hive partitioning
# (mode=AUTO) で参照する。
################################################################################

resource "google_bigquery_dataset" "raw" {
  project       = var.project_id
  dataset_id    = var.bq_raw_dataset
  location      = var.bq_location
  friendly_name = "analytics-platform raw"
  description   = "Raw JSONL events read via external table over GCS Hive partitioning."

  labels = {
    component = "analytics-platform"
    layer     = "raw"
  }
}

resource "google_bigquery_dataset" "staging" {
  project       = var.project_id
  dataset_id    = var.bq_staging_dataset
  location      = var.bq_location
  friendly_name = "analytics-platform staging"
  description   = "dbt staging views (cross-DB compatible SQL)."

  labels = {
    component = "analytics-platform"
    layer     = "staging"
  }
}

resource "google_bigquery_dataset" "marts" {
  project       = var.project_id
  dataset_id    = var.bq_marts_dataset
  location      = var.bq_location
  friendly_name = "analytics-platform marts"
  description   = "dbt marts (KPIs / cache efficiency / delivery health)."

  labels = {
    component = "analytics-platform"
    layer     = "marts"
  }
}

resource "google_bigquery_table" "agent_events_external" {
  count = var.create_bq_external_table ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.raw.dataset_id
  table_id   = var.bq_external_table_name

  # external table は表自体を delete しても GCS データは無傷
  deletion_protection = false

  description = "External table over gs://${local.raw_bucket_name}/${var.gcs_raw_prefix}/ Hive partitioning."

  external_data_configuration {
    autodetect            = true
    source_format         = "NEWLINE_DELIMITED_JSON"
    ignore_unknown_values = true

    source_uris = [
      "gs://${google_storage_bucket.raw.name}/${var.gcs_raw_prefix}/*",
    ]

    hive_partitioning_options {
      mode              = "AUTO"
      source_uri_prefix = "gs://${google_storage_bucket.raw.name}/${var.gcs_raw_prefix}/"
    }
  }

  labels = {
    component = "analytics-platform"
    layer     = "raw"
  }
}
