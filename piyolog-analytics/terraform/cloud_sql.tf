################################################################################
# Cloud SQL (Postgres) — piyolog-analytics の永続化先
#
# 設計:
#   - 家族 2 人分のトラフィックなので tier=db-f1-micro / ZONAL で月額 ~$10。
#   - public IP + authorized network なし。Cloud Run は connector 経由で接続するので
#     network ingress は閉じている (Cloud SQL Auth Proxy / connector のみ)。
#   - DB password は random_password で TF が生成 → Secret Manager に流す。
#   - 削除保護は本番想定で default true。dev は tfvars で false に上書き。
################################################################################

resource "random_password" "cloud_sql_db_password" {
  length  = 32
  special = true
  # `:`, `@`, `/` は SQLAlchemy URL のセパレータと衝突するため除外
  override_special = "!#$%^&*()-_=+[]{};,.<>?"
}

resource "google_sql_database_instance" "piyolog" {
  project          = var.project_id
  name             = local.cloud_sql_instance_name
  region           = var.region
  database_version = var.cloud_sql_database_version

  deletion_protection = var.cloud_sql_deletion_protection

  settings {
    tier              = var.cloud_sql_tier
    availability_type = var.cloud_sql_availability
    disk_size         = var.cloud_sql_disk_size
    disk_autoresize   = true
    disk_type         = "PD_SSD"

    backup_configuration {
      enabled                        = var.cloud_sql_backup_enabled
      point_in_time_recovery_enabled = false
      start_time                     = "18:00" # JST 03:00
    }

    ip_configuration {
      ipv4_enabled    = true # Cloud SQL Auth Proxy / Cloud Run connector が使う public IP
      ssl_mode        = "ENCRYPTED_ONLY"
      private_network = null
    }

    database_flags {
      name  = "max_connections"
      value = "50"
    }

    user_labels = {
      component = "piyolog-analytics"
    }
  }
}

resource "google_sql_database" "piyolog" {
  project  = var.project_id
  instance = google_sql_database_instance.piyolog.name
  name     = var.cloud_sql_db_name
}

resource "google_sql_user" "piyolog" {
  project  = var.project_id
  instance = google_sql_database_instance.piyolog.name
  name     = var.cloud_sql_db_user
  password = random_password.cloud_sql_db_password.result
}
