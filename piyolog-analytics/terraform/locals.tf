locals {
  # 命名規則: ${name_prefix}-... で揃える
  cloud_sql_instance_name = var.name_prefix
  sa_piyolog_id           = "sa-${var.name_prefix}"
  sa_piyolog_email        = google_service_account.piyolog.email

  # TODO(PROPOSAL-0009 P1): 共有インスタンスへの移行が完了したら、
  #   var.cloud_sql_use_shared_instance フラグと専用インスタンス側の分岐
  #   (google_sql_database_instance.piyolog / 下記三項の `:` 側) を削除し、
  #   共有インスタンス前提 (data source 直参照) に簡約する。
  #   対象: 下記 3 つの local + cloud_sql.tf (count ゲート / data source)
  #         + variables.tf (フラグ変数)。

  # 専用 / 共有モードで実際にアタッチするインスタンスを解決する (PROPOSAL-0009 P1)。
  # one(<splat>) は count=0 で null、count=1 で要素を返すため、count 切替時の
  # index out-of-range を避けられる (conditional の非選択側でもエラーにならない)。
  cloud_sql_instance_ref = (
    var.cloud_sql_use_shared_instance
    ? one(data.google_sql_database_instance.shared[*].name)
    : one(google_sql_database_instance.piyolog[*].name)
  )

  # Cloud SQL connection name (project:region:instance)
  cloud_sql_connection_name = (
    var.cloud_sql_use_shared_instance
    ? one(data.google_sql_database_instance.shared[*].connection_name)
    : one(google_sql_database_instance.piyolog[*].connection_name)
  )

  # Cloud SQL instance の管理 SA (export/import 用の bucket 権限付与に使う)。
  cloud_sql_service_account_email = (
    var.cloud_sql_use_shared_instance
    ? one(data.google_sql_database_instance.shared[*].service_account_email_address)
    : one(google_sql_database_instance.piyolog[*].service_account_email_address)
  )

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
    local.cloud_sql_connection_name,
  )
}
