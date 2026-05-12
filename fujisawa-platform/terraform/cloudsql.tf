# Phase 4-2h step 2: Cloud SQL Database + ETL user。
#
# 設計方針 (proposal 0003 §4.5 / §4.5.3):
# - **driving-license-bot の Cloud SQL instance を共有** (月 ¥0 増)。本 terraform では
#   instance 自体は作らず、`data` source で参照 + `google_sql_database` で
#   fujisawa_kb_db を追加するだけ。
# - ETL 用ユーザ (`fujisawa_etl_user`) を新規作成。INSERT / UPSERT / DELETE 権限は
#   psql で `GRANT ... TO etl_role` を流すことで付与 (docs/SETUP.md §4 参照)。
# - consumer (info-bot / 保活) 用ユーザは consumer 側の terraform で別途作成。
# - password は random_password で生成し Secret Manager に格納。

# 既存 instance への data 参照 (terraform-managed である必要なし、名前があれば OK)
data "google_sql_database_instance" "shared" {
  project = var.project_id
  name    = var.shared_cloudsql_instance_name

  depends_on = [google_project_service.sqladmin]
}

# fujisawa_kb_db database を共有 instance に追加
resource "google_sql_database" "kb" {
  project  = var.project_id
  name     = local.cloudsql_database_name
  instance = data.google_sql_database_instance.shared.name

  # ABANDON: terraform から database delete API を呼ばない。instance destroy で
  # 巻き取らせる (driving-license-bot と同方針)。app user が所有するオブジェクトとの
  # 依存で delete がこける可能性があるため。
  deletion_policy = "ABANDON"
}

# pgvector extension は driving-license-bot の Phase 1 で既に有効化済の想定。
# 未有効化なら手動で `CREATE EXTENSION IF NOT EXISTS vector;` を fujisawa_kb_db に
# 流す必要あり (docs/SETUP.md §4 参照)。

# ETL 用ユーザの password を random で生成
resource "random_password" "etl_user" {
  length  = 32
  special = true
  # postgres password で扱いづらい記号は除外
  override_special = "!#$%&*()-_=+[]{}<>?"
}

# ETL 用 PostgreSQL ユーザを作成 (instance スコープ、DB スコープではない)
resource "google_sql_user" "etl" {
  project  = var.project_id
  name     = local.cloudsql_etl_user_name
  instance = data.google_sql_database_instance.shared.name
  password = random_password.etl_user.result

  # ABANDON: user 削除も instance destroy で巻き取らせる。user が所有する
  # オブジェクトとの依存で delete がこけるのを回避するため。
  deletion_policy = "ABANDON"
}

# Secret Manager に password を投入 (secrets.tf で secret 枠を定義)
resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.etl_user.result
}
