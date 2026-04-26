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
