# Phase 2-A1: Cloud SQL Postgres + pgvector の重複検査基盤。
#
# PROPOSAL-0009 P1 (コスト集約): この instance はモノレポの **共有 Cloud SQL**。
#   driving-license-bot 本体 (question_bank) に加え、fujisawa_kb_db (ETL/consumer)、
#   piyolog (cloud_sql_use_shared_instance=true 時) が同居する。複数アプリ + pgvector の
#   ため tier 既定を db-g1-small (1.7GB) に引き上げ、max_connections を明示設定している。
#   tier / max_connections 変更は instance 再起動 (短時間の接続断) を伴う。
#
# 設計方針:
# - tier=db-g1-small (共有用)。単独運用に戻すなら db-f1-micro でも可 (cloudsql_tier で変更)。
# - PUBLIC IP + Cloud SQL Auth Proxy 接続。VPC Connector / Private IP は Phase 3+ に
#   先送り（INFRASTRUCTURE.md §5）。authorized_networks は既定で空（IP 直接公開はしない）。
# - SSL `ENCRYPTED_ONLY` で平文接続を拒否。Auth Proxy は内部で TLS を張る。
# - 自動バックアップは既定で有効（コスト微増だが復旧手段として有用）。
# - PITR / HA (REGIONAL) は PoC では無効。コスト 2 倍化を避ける。
# - password は random_password で生成し Secret Manager に格納。tfstate に値が残る点は
#   PoC として容認（tfstate バケットは private + versioning 済）。本番化時は
#   Secret Manager に手動投入 + lifecycle で random を切り離す運用に変更。
#
# 接続情報（apply 後）:
#   instance_connection_name = "${PROJECT}:${REGION}:${var.name_prefix}-pg"
#   database = "question_bank"
#   user     = "app"
#   password = `gcloud secrets versions access latest --secret=driving-license-bot-cloudsql-password`
#
# スキーマ作成は次 PR (A2) の `scripts/init_question_bank_schema.py` で行う。

resource "random_password" "cloudsql_app" {
  length  = 32
  special = true
  # postgres password で扱いづらい記号は除外（@ : / は接続文字列で意味を持つ）
  override_special = "!#$%&*()-_=+[]{}<>?"
}

resource "google_sql_database_instance" "main" {
  project          = var.project_id
  name             = local.cloudsql_instance_name
  region           = var.region
  database_version = "POSTGRES_15"

  deletion_protection = var.cloudsql_deletion_protection

  settings {
    tier              = var.cloudsql_tier
    disk_size         = var.cloudsql_disk_size_gb
    disk_type         = "PD_SSD"
    disk_autoresize   = false
    availability_type = "ZONAL"

    user_labels = local.labels

    ip_configuration {
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"

      dynamic "authorized_networks" {
        for_each = var.cloudsql_authorized_networks
        content {
          name  = authorized_networks.value.name
          value = authorized_networks.value.value
        }
      }
    }

    backup_configuration {
      enabled                        = var.cloudsql_backup_enabled
      start_time                     = "16:00" # JST 01:00
      point_in_time_recovery_enabled = false
      transaction_log_retention_days = 1
      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
    }

    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "off"
    }

    insights_config {
      query_insights_enabled = true
    }
  }

  depends_on = [google_project_service.sqladmin]
}

resource "google_sql_database" "question_bank" {
  project  = var.project_id
  name     = local.cloudsql_database_name
  instance = google_sql_database_instance.main.name

  # ABANDON: terraform から database delete API を呼ばない。instance destroy で
  # 巻き取らせる。app user が所有する 200+ オブジェクトとの依存で delete が
  # こけるのを回避するため。state からは消えるので次回 apply で再作成される。
  deletion_policy = "ABANDON"
}

resource "google_sql_user" "app" {
  project  = var.project_id
  name     = local.cloudsql_user_name
  instance = google_sql_database_instance.main.name
  password = random_password.cloudsql_app.result

  # ABANDON: 同上。user が所有するオブジェクトとの依存で delete がこけるため
  # delete API を呼ばず instance destroy で巻き取らせる。
  deletion_policy = "ABANDON"
}

# Secret Manager に投入。accessor 権限の付与は Phase 2-A3 (sa-batch / sa-agent 作成時) で行う。
resource "google_secret_manager_secret_version" "cloudsql_password" {
  secret      = google_secret_manager_secret.cloudsql_password.id
  secret_data = random_password.cloudsql_app.result
}
