################################################################################
# Step 3: GCS buckets + ライフサイクルルール
#
# - raw:         Hive パーティションの JSONL (BigQuery external table のソース)
# - payloads:    8KB 超の大容量コンテンツ (content_uri = gs://...)
# - dead_letter: スキーマ違反等で取込失敗した JSONL
#
# ライフサイクル (raw / payloads):
#   0-30d   STANDARD   ホット分析
#   30-90d  NEARLINE   月次集計
#   90-365d COLDLINE   監査
#   365d-   ARCHIVE    長期保存
#
# dead_letter は短めのリテンションで自動削除 (default 90 日) する。
################################################################################

# Public access はデフォルト OFF (uniform bucket-level access)
locals {
  # raw / payloads に共通のライフサイクル
  raw_lifecycle_rules = concat(
    var.lifecycle_nearline_days > 0 ? [{
      action_type          = "SetStorageClass"
      action_storage_class = "NEARLINE"
      age                  = var.lifecycle_nearline_days
    }] : [],
    var.lifecycle_coldline_days > 0 ? [{
      action_type          = "SetStorageClass"
      action_storage_class = "COLDLINE"
      age                  = var.lifecycle_coldline_days
    }] : [],
    var.lifecycle_archive_days > 0 ? [{
      action_type          = "SetStorageClass"
      action_storage_class = "ARCHIVE"
      age                  = var.lifecycle_archive_days
    }] : [],
  )
}

resource "google_storage_bucket" "raw" {
  name                        = local.raw_bucket_name
  project                     = var.project_id
  location                    = var.gcs_bucket_location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.gcs_force_destroy

  versioning {
    enabled = false
  }

  dynamic "lifecycle_rule" {
    for_each = local.raw_lifecycle_rules
    content {
      action {
        type          = lifecycle_rule.value.action_type
        storage_class = lifecycle_rule.value.action_storage_class
      }
      condition {
        age = lifecycle_rule.value.age
      }
    }
  }

  labels = {
    component = "analytics-platform"
    purpose   = "raw-jsonl"
  }
}

resource "google_storage_bucket" "payloads" {
  name                        = local.payloads_bucket_name
  project                     = var.project_id
  location                    = var.gcs_bucket_location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.gcs_force_destroy

  dynamic "lifecycle_rule" {
    for_each = local.raw_lifecycle_rules
    content {
      action {
        type          = lifecycle_rule.value.action_type
        storage_class = lifecycle_rule.value.action_storage_class
      }
      condition {
        age = lifecycle_rule.value.age
      }
    }
  }

  labels = {
    component = "analytics-platform"
    purpose   = "large-payload"
  }
}

resource "google_storage_bucket" "dead_letter" {
  name                        = local.dead_letter_bucket_name
  project                     = var.project_id
  location                    = var.gcs_bucket_location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.gcs_force_destroy

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = var.lifecycle_dead_letter_delete_days
    }
  }

  labels = {
    component = "analytics-platform"
    purpose   = "dead-letter"
  }
}
