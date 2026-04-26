locals {
  # 命名規則: ${name_prefix}-... で揃える
  cloud_sql_instance_name = var.name_prefix
  sa_piyolog_id           = "sa-${var.name_prefix}"
  sa_piyolog_email        = google_service_account.piyolog.email

  # Cloud SQL connection name (project:region:instance)
  cloud_sql_connection_name = google_sql_database_instance.piyolog.connection_name

  # Secret Manager IDs
  secret_line_channel_secret       = "${var.name_prefix}-line-channel-secret"
  secret_line_channel_access_token = "${var.name_prefix}-line-channel-access-token"
  secret_database_url              = "${var.name_prefix}-database-url"

  # SQLAlchemy URL (Cloud Run + Cloud SQL Unix socket)
  database_url = format(
    "postgresql+asyncpg://%s:%s@/%s?host=/cloudsql/%s",
    var.cloud_sql_db_user,
    random_password.cloud_sql_db_password.result,
    var.cloud_sql_db_name,
    google_sql_database_instance.piyolog.connection_name,
  )
}
