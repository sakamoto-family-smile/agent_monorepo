variable "project_id" {
  type        = string
  description = "GCP project id."
}

variable "region" {
  type        = string
  description = "Default region for Cloud SQL / Artifact Registry / Cloud Run."
  default     = "us-central1"
}

variable "name_prefix" {
  type        = string
  description = "Prefix for resource names (Cloud SQL instance, SA, AR repo, secrets)."
  default     = "piyolog"
}

# ---- Cloud SQL ----

# PROPOSAL-0009 P1: Cloud SQL 集約。
# true にすると piyolog 専用インスタンスを作らず、既存の共有インスタンス
# (共有インスタンス shared-pg) に piyolog DB / user を相乗りさせる。
# false (既定) は従来どおり専用インスタンスを作成 = 後方互換。
# 切替はデータ移行 (dump → restore) を伴う。terraform/README.md の移行手順参照。
# TODO(PROPOSAL-0009 P1): 全環境が共有インスタンスへ移行したら、このフラグと
#   shared_cloudsql_instance_name 以外の専用インスタンス用変数 (cloud_sql_tier /
#   _disk_size / _availability / _database_version 等) を整理し、共有前提に簡約する。
variable "cloud_sql_use_shared_instance" {
  type        = bool
  description = "true で既存の共有 Cloud SQL instance に相乗り (PROPOSAL-0009 P1)。false で専用インスタンスを作成。"
  default     = false
}

variable "shared_cloudsql_instance_name" {
  type        = string
  description = "相乗り先の既存 Cloud SQL instance 名 (PROPOSAL-0009 P1: shared-pg)。cloud_sql_use_shared_instance=true のとき必須。"
  default     = ""
}

variable "cloud_sql_tier" {
  type        = string
  description = "Cloud SQL machine tier. db-f1-micro for family / dev, db-g1-small for moderate prod."
  default     = "db-f1-micro"
}

variable "cloud_sql_database_version" {
  type        = string
  description = "Postgres version (POSTGRES_15 / POSTGRES_16)."
  default     = "POSTGRES_15"
}

variable "cloud_sql_disk_size" {
  type        = number
  description = "Disk size in GB. Auto-resize is enabled, this is the floor."
  default     = 10
}

variable "cloud_sql_availability" {
  type        = string
  description = "ZONAL (cheaper) or REGIONAL (HA)."
  default     = "ZONAL"
}

variable "cloud_sql_deletion_protection" {
  type        = bool
  description = "Set true in prod to prevent accidental deletion."
  default     = true
}

variable "cloud_sql_backup_enabled" {
  type        = bool
  description = "Enable automated daily backup."
  default     = true
}

variable "cloud_sql_db_name" {
  type        = string
  description = "Database name created inside the Cloud SQL instance."
  default     = "piyolog"
}

variable "cloud_sql_db_user" {
  type        = string
  description = "Database user."
  default     = "piyolog"
}

# ---- Artifact Registry ----

variable "ar_repo_name" {
  type        = string
  description = "Artifact Registry Docker repo name. Used by cloudbuild.yaml + deploy_cloud_run.sh."
  default     = "piyolog-analytics"
}

# ---- LINE secrets (Phase B3 では空 secret container だけ作る) ----

variable "create_line_secret_versions" {
  type        = bool
  description = "If true, create empty initial versions for LINE secrets. Otherwise add via gcloud manually."
  default     = false
}

variable "line_channel_secret_value" {
  type        = string
  description = "LINE Messaging API channel secret. Only used when create_line_secret_versions=true."
  default     = ""
  sensitive   = true
}

variable "line_channel_access_token_value" {
  type        = string
  description = "LINE Messaging API channel access token. Only used when create_line_secret_versions=true."
  default     = ""
  sensitive   = true
}

# ---- Phase 4-A: Backup bucket ----

variable "backup_retention_days" {
  type        = number
  description = "GCS backup bucket の current version 保持日数 (lifecycle で自動削除)。"
  default     = 90
}

variable "backup_bucket_force_destroy" {
  type        = bool
  description = "true で `terraform destroy` 時に backup bucket もオブジェクトごと削除。既定 false で backup を保護。"
  default     = false
}
