variable "project_id" {
  type        = string
  description = "GCP project id (driving-license-bot と同 project を推奨、Cloud SQL instance 共有のため)。"
}

variable "region" {
  type        = string
  description = "Default region for regional resources."
  default     = "asia-northeast1"
}

variable "name_prefix" {
  type        = string
  description = "Resource name prefix to scope all fujisawa-platform resources."
  default     = "fujisawa"
}

# ─────────────────────────────────────────────────────────────────────
# Cloud SQL (driving-license-bot の instance を共有する)
# ─────────────────────────────────────────────────────────────────────

variable "shared_cloudsql_instance_name" {
  type        = string
  description = "既存の Cloud SQL Postgres instance 名 (driving-license-bot の例: driving-license-bot-pg)。fujisawa_kb_db DB はこの instance に追加される。"
}

variable "shared_cloudsql_instance_connection_name" {
  type        = string
  description = "既存 Cloud SQL instance の connection name (project:region:instance 形式)。Cloud Run Job の Cloud SQL connector で利用 (step 3)。"
}

# ─────────────────────────────────────────────────────────────────────
# PdfArchive
# ─────────────────────────────────────────────────────────────────────

variable "pdf_archive_bucket_location" {
  type        = string
  description = "GCS bucket location for fujisawa-pdf-archive."
  default     = "ASIA-NORTHEAST1"
}

variable "pdf_archive_bucket_lifecycle_age_days" {
  type        = number
  description = "PDF アーカイブの自動削除日数 (proposal §4.5 では明記なし、コスト最適化目的で 1095 日 = 3 年を default)。0 で無効化。"
  default     = 1095
}

# ─────────────────────────────────────────────────────────────────────
# Artifact Registry
# ─────────────────────────────────────────────────────────────────────

variable "artifact_registry_image_retention_count" {
  type        = number
  description = "Docker image の保持数 (古いものから削除)。0 で無効化。"
  default     = 10
}

# ─────────────────────────────────────────────────────────────────────
# IAM
# ─────────────────────────────────────────────────────────────────────

variable "consumer_service_account_emails" {
  type        = list(string)
  description = "fujisawa_kb_db に SELECT アクセスを許可する consumer SA (info-bot / 保活)。空 list なら付与せず、別途手動で追加。"
  default     = []
}

# ─────────────────────────────────────────────────────────────────────
# Vertex AI
# ─────────────────────────────────────────────────────────────────────

variable "vertex_location" {
  type        = string
  description = "Vertex AI location (text-embedding-004 のリージョン)。"
  default     = "us-central1"
}
