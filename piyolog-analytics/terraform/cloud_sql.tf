################################################################################
# Cloud SQL (Postgres) — piyolog-analytics の永続化先
#
# 設計:
#   - 家族 2 人分のトラフィックなので tier=db-f1-micro / ZONAL で月額 ~$10。
#   - public IP + authorized network なし。Cloud Run は connector 経由で接続するので
#     network ingress は閉じている (Cloud SQL Auth Proxy / connector のみ)。
#   - DB password は random_password で TF が生成 → Secret Manager に流す。
#   - 削除保護は本番想定で default true。dev は tfvars で false に上書き。
#
# PROPOSAL-0009 P1 (コスト集約):
#   - cloud_sql_use_shared_instance=true で専用インスタンスを作らず、既存の共有
#     インスタンス (driving-license-bot-pg 等) に piyolog DB / user を相乗りさせる
#     (fujisawa-platform / fujisawa-info-bot と同じ data 参照パターン)。
#   - DB / user は deletion_policy=ABANDON。共有インスタンス上のデータを terraform の
#     delete API で消さず、instance destroy 時に巻き取らせる (誤削除防止)。
#   - 移行手順 (dump → restore / state mv) は terraform/README.md 参照。
################################################################################

resource "random_password" "cloud_sql_db_password" {
  length  = 32
  special = true
  # `:`, `@`, `/` は SQLAlchemy URL のセパレータと衝突するため除外
  override_special = "!#$%^&*()-_=+[]{};,.<>?"
}

# TODO(PROPOSAL-0009 P1): 移行完了後は共有インスタンス前提に簡約する。
#   - この data source の count ゲートを外して常時参照に
#   - 下の google_sql_database_instance.piyolog (専用インスタンス) を丸ごと削除
#   - var.cloud_sql_use_shared_instance を撤去 (locals.tf / variables.tf も同様)

# 相乗り先の既存インスタンス (cloud_sql_use_shared_instance=true のときだけ参照)。
data "google_sql_database_instance" "shared" {
  count   = var.cloud_sql_use_shared_instance ? 1 : 0
  project = var.project_id
  name    = var.shared_cloudsql_instance_name
}

# 専用インスタンス (cloud_sql_use_shared_instance=false のときだけ作成)。
# TODO(PROPOSAL-0009 P1): 移行完了後にこのリソースごと削除する。
resource "google_sql_database_instance" "piyolog" {
  count = var.cloud_sql_use_shared_instance ? 0 : 1

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

    # NOTE: この max_connections は専用モード (cloud_sql_use_shared_instance=false)
    # のときだけ有効。共有モードではこの instance 自体が作られない (count=0) ため、
    # 実効上限は共有先インスタンス (driving-license-bot の cloudsql_max_connections)
    # で決まる。PROPOSAL-0009 P1 / terraform/README.md「Cloud SQL 集約」参照。
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
  instance = local.cloud_sql_instance_ref
  name     = var.cloud_sql_db_name

  # 共有インスタンス上で誤って DB を消さない (instance destroy で巻き取り)。
  deletion_policy = "ABANDON"
}

resource "google_sql_user" "piyolog" {
  project  = var.project_id
  instance = local.cloud_sql_instance_ref
  name     = var.cloud_sql_db_user
  password = random_password.cloud_sql_db_password.result

  deletion_policy = "ABANDON"
}
