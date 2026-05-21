# fujisawa_kb_db の consumer 用 SQL user。
#
# fujisawa-platform が同 instance / 同 DB を既に terraform 管理しているため、
# 本ファイルは **user の追加のみ**。 SELECT 権限の GRANT は psql で別途流す
# (docs/SETUP.md §4 参照)。

data "google_sql_database_instance" "shared" {
  name    = var.shared_cloudsql_instance_name
  project = var.project_id
}

resource "google_sql_user" "consumer" {
  project  = var.project_id
  name     = local.cloudsql_consumer_user_name
  instance = data.google_sql_database_instance.shared.name
  password = random_password.kb_db_consumer.result

  # fujisawa-platform 側の etl_user と同じく、 user 削除も instance destroy で
  # 巻き取らせる方針。
  lifecycle {
    prevent_destroy = false
  }

  depends_on = [google_project_service.sqladmin]
}
