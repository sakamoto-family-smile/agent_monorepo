variable "project_id" {
  type        = string
  description = "GCP project id (driving-license-bot と同 project を推奨、Cloud SQL instance 共有のため)。"
}

variable "region" {
  type        = string
  description = "Default region for regional resources."
  default     = "asia-northeast1"
}

variable "name_prefix" {
  type        = string
  description = "Resource name prefix to scope all fujisawa-platform resources."
  default     = "fujisawa"
}

# ─────────────────────────────────────────────────────────────────────
# Cloud SQL (driving-license-bot の instance を共有する)
# ─────────────────────────────────────────────────────────────────────

variable "shared_cloudsql_instance_name" {
  type        = string
  description = "既存の共有 Cloud SQL Postgres instance 名 (PROPOSAL-0009 P1: shared-pg)。fujisawa_kb_db DB はこの instance に追加される。"
}

variable "shared_cloudsql_instance_connection_name" {
  type        = string
  description = "既存 Cloud SQL instance の connection name (project:region:instance 形式)。Cloud Run Job の Cloud SQL connector で利用 (step 3)。"
}

# ─────────────────────────────────────────────────────────────────────
# PdfArchive
# ─────────────────────────────────────────────────────────────────────

variable "pdf_archive_bucket_location" {
  type        = string
  description = "GCS bucket location for fujisawa-pdf-archive."
  default     = "ASIA-NORTHEAST1"
}

variable "pdf_archive_bucket_lifecycle_age_days" {
  type        = number
  description = "PDF アーカイブの自動削除日数 (proposal §4.5 では明記なし、コスト最適化目的で 1095 日 = 3 年を default)。0 で無効化。"
  default     = 1095
}

# ─────────────────────────────────────────────────────────────────────
# Artifact Registry
# ─────────────────────────────────────────────────────────────────────

variable "artifact_registry_image_retention_count" {
  type        = number
  description = "Docker image の保持数 (古いものから削除)。0 で無効化。"
  default     = 10
}

# ─────────────────────────────────────────────────────────────────────
# IAM
# ─────────────────────────────────────────────────────────────────────

variable "consumer_service_account_emails" {
  type        = list(string)
  description = "fujisawa_kb_db に SELECT アクセスを許可する consumer SA (info-bot / 保活)。空 list なら付与せず、別途手動で追加。"
  default     = []
}

# ─────────────────────────────────────────────────────────────────────
# Vertex AI
# ─────────────────────────────────────────────────────────────────────

variable "vertex_location" {
  type        = string
  description = "Vertex AI location (text-embedding-004 のリージョン)。"
  default     = "us-central1"
}

# ─────────────────────────────────────────────────────────────────────
# Cloud Run Jobs (step 3)
# ─────────────────────────────────────────────────────────────────────

variable "etl_image" {
  type        = string
  description = "Cloud Run Jobs で使う Docker image URI (Artifact Registry)。空文字列なら Cloud Run Jobs と Scheduler の deploy をスキップ (chicken-and-egg: image を build してから埋める)。"
  default     = ""
}

variable "etl_job_cpu" {
  type        = string
  description = "Cloud Run Job CPU 数。"
  default     = "1"
}

variable "etl_job_memory" {
  type        = string
  description = "Cloud Run Job memory。Docling pipeline (rapidocr + tableformer + layout-heron 同時 load) で 2Gi だと OOM (exit 137) するため 4Gi 確保。 2026-05-14 実 GCP 実行で wayback_backfill が 2Gi で OOM、 手動 4Gi bump で復旧確認済。"
  default     = "4Gi"
}

variable "etl_job_task_timeout_seconds" {
  type        = number
  description = "Cloud Run Job タスクタイムアウト (秒)。 2026-05-21 改訂: weekly_crawl の差分 crawl 化に伴い、 初回 full crawl (sitemap 7,906 URL × GET 3s ≈ 6.6 時間) を吸収するため 8 時間 (28,800s) に拡張。 通常週次は HEAD + 数百 GET で ~1〜2 時間で完走するため余裕。"
  default     = 28800
}

variable "etl_job_max_retries" {
  type        = number
  description = "Cloud Run Job のタスクリトライ回数。run_etl_job の fail-fast 機構があるので 0 で OK。"
  default     = 0
}

variable "etl_min_interval_sec" {
  type        = number
  description = "PoliteFetcher の GET 連続リクエスト最小間隔 (秒)。 藤沢市 HP は 3.0 を default。 緊急時のみ短縮を検討。"
  default     = 3.0
}

variable "etl_min_interval_sec_head" {
  type        = number
  description = "PoliteFetcher の HEAD 連続リクエスト最小間隔 (秒)。 weekly_crawl の差分 crawl で 7,906 URL を 1 時間程度で HEAD チェック完了するため 0.5 秒。 HEAD はボディ転送無しなので GET より短く設定可能。"
  default     = 0.5
}

variable "etl_sitemap_url" {
  type        = string
  description = "weekly_crawl_etl の sitemap.xml URL (env: FUJISAWA_ETL_SITEMAP_URL)。"
  default     = "https://www.city.fujisawa.kanagawa.jp/sitemap.xml"
}

variable "etl_authorized_facilities_url" {
  type        = string
  description = "half_yearly_facility_etl の認可施設一覧 HTML URL (env: FUJISAWA_ETL_AUTHORIZED_FACILITIES_URL)。 2026-05-15 sitemap 探索で確定。"
  default     = "https://www.city.fujisawa.kanagawa.jp/hoiku/kenko/kosodate/hoikuen/ninka-ichiran.html"
}

variable "etl_unauthorized_facilities_url" {
  type        = string
  description = "half_yearly_facility_etl の認可外施設一覧 HTML URL (env: FUJISAWA_ETL_UNAUTHORIZED_FACILITIES_URL)。 2026-05-15 sitemap 探索で確定。"
  default     = "https://www.city.fujisawa.kanagawa.jp/hoiku/kenko/kosodate/hoikuen/shisetsu.html"
}

variable "etl_navi_pdf_url" {
  type        = string
  description = "yearly_navi_etl の申込ナビ PDF URL。"
  default     = ""
}

variable "etl_admission_pdf_url_1st" {
  type        = string
  description = "biyearly_admission_etl の 1 次入所結果 PDF URL。"
  default     = ""
}

variable "etl_admission_pdf_url_2nd" {
  type        = string
  description = "biyearly_admission_etl の 2 次入所結果 PDF URL。"
  default     = ""
}

variable "etl_admission_year" {
  type        = number
  description = "biyearly_admission_etl の対象年度 (西暦)。"
  default     = 2026
}

# ─────────────────────────────────────────────────────────────────────
# Cloud Scheduler (step 3)
# ─────────────────────────────────────────────────────────────────────

variable "scheduler_time_zone" {
  type        = string
  description = "Cloud Scheduler のタイムゾーン。"
  default     = "Asia/Tokyo"
}

variable "scheduler_weekly_crawl_schedule" {
  type        = string
  description = "weekly_crawl_etl の cron 式 (default: 毎週日曜 03:00 JST)。"
  default     = "0 3 * * 0"
}

variable "scheduler_monthly_vacancy_schedule" {
  type        = string
  description = "monthly_vacancy_etl の cron 式 (default: 毎月 22 日 03:00 JST)。"
  default     = "0 3 22 * *"
}

variable "scheduler_monthly_stats_compute_schedule" {
  type        = string
  description = "monthly_stats_compute の cron 式 (default: 毎月 23 日 03:00 JST、vacancy 完了後)。"
  default     = "0 3 23 * *"
}

variable "scheduler_half_yearly_facility_schedule" {
  type        = string
  description = "half_yearly_facility_etl の cron 式 (default: 4 月・10 月 1 日 03:00 JST)。"
  default     = "0 3 1 4,10 *"
}

variable "scheduler_yearly_navi_schedule" {
  type        = string
  description = "yearly_navi_etl の cron 式 (default: 4 月・10 月 1 日 03:00 JST)。"
  default     = "0 3 1 4,10 *"
}

variable "scheduler_biyearly_admission_1st_schedule" {
  type        = string
  description = "biyearly_admission_etl 1 次 の cron 式 (default: 2 月 25 日 03:00 JST、1 次内定発表後)。"
  default     = "0 3 25 2 *"
}

variable "scheduler_biyearly_admission_2nd_schedule" {
  type        = string
  description = "biyearly_admission_etl 2 次 の cron 式 (default: 3 月 25 日 03:00 JST、2 次内定発表後)。"
  default     = "0 3 25 3 *"
}
