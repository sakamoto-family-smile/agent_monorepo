# Cloud SQL (Postgres) — stock-analysis-agent の永続化先 (PROPOSAL-0011 P2-B)。
#
# PROPOSAL-0009 P1 で集約済の共有インスタンス (shared-pg) に、stock 専用の
# database + user を相乗りさせる (piyolog / fujisawa-info-bot と同パターン)。
# 専用インスタンスは作らない。
#
# DB / user は deletion_policy=ABANDON: terraform destroy で共有インスタンス上の
# データを消さず、instance destroy 時に巻き取らせる (誤削除防止)。

data "google_sql_database_instance" "shared" {
  project = var.project_id
  name    = var.shared_cloudsql_instance_name
}

resource "random_password" "db_password" {
  length = 32
  # SQLAlchemy URL のセパレータ衝突を避けつつ percent-encode 前提で special も許可。
  # `:` `@` `/` `?` `#` は URL を壊しやすいので除外する。
  special          = true
  override_special = "!$%^&*()-_=+[]{};,."
}

resource "google_sql_database" "stock" {
  project         = var.project_id
  instance        = data.google_sql_database_instance.shared.name
  name            = var.db_name
  deletion_policy = "ABANDON"
}

resource "google_sql_user" "stock" {
  project         = var.project_id
  instance        = data.google_sql_database_instance.shared.name
  name            = var.db_user
  password        = random_password.db_password.result
  deletion_policy = "ABANDON"

  depends_on = [google_project_service.sqladmin]
}
