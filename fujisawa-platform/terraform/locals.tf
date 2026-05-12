locals {
  # ─── Labels (全リソース共通) ───────────────────────────────────────
  labels = {
    project    = "fujisawa-platform"
    managed_by = "terraform"
  }

  # ─── Cloud SQL ─────────────────────────────────────────────────────
  cloudsql_database_name = "fujisawa_kb_db"
  cloudsql_etl_user_name = "${var.name_prefix}_etl_user"

  # ─── Service Account ───────────────────────────────────────────────
  sa_etl_id    = "sa-fujisawa-etl"
  sa_etl_email = google_service_account.etl.email

  # ─── Secret Manager (値は手動投入。terraform は枠のみ) ───────────
  secret_db_password    = "${var.name_prefix}-etl-db-password"
  secret_user_agent     = "${var.name_prefix}-etl-user-agent"
  secret_vertex_project = "${var.name_prefix}-etl-vertex-project"

  # ─── GCS bucket (PdfArchive) ───────────────────────────────────────
  pdf_archive_bucket_name = "${var.name_prefix}-pdf-archive-${var.project_id}"

  # ─── Artifact Registry ─────────────────────────────────────────────
  artifact_registry_repo_id = "${var.name_prefix}-etl"

  # ─── Cloud Run Jobs (step 3) ───────────────────────────────────────
  # image が空文字列なら Cloud Run Jobs と Scheduler を deploy しない
  # (chicken-and-egg: image を build してから埋める)
  deploy_jobs = var.etl_image != ""

  # 7 Job の定義。`scheduler_name` が空なら手動 trigger only (wayback_backfill)。
  etl_jobs = {
    weekly_crawl = {
      name           = "${var.name_prefix}-weekly-crawl"
      args           = ["weekly_crawl"]
      scheduler_name = "${var.name_prefix}-weekly-crawl-sched"
      cron           = var.scheduler_weekly_crawl_schedule
    }
    half_yearly_facility = {
      name           = "${var.name_prefix}-half-yearly-facility"
      args           = ["half_yearly_facility"]
      scheduler_name = "${var.name_prefix}-half-yearly-facility-sched"
      cron           = var.scheduler_half_yearly_facility_schedule
    }
    biyearly_admission_1st = {
      name           = "${var.name_prefix}-biyearly-admission-1st"
      args           = ["biyearly_admission", "--round", "1st"]
      scheduler_name = "${var.name_prefix}-biyearly-admission-1st-sched"
      cron           = var.scheduler_biyearly_admission_1st_schedule
    }
    biyearly_admission_2nd = {
      name           = "${var.name_prefix}-biyearly-admission-2nd"
      args           = ["biyearly_admission", "--round", "2nd"]
      scheduler_name = "${var.name_prefix}-biyearly-admission-2nd-sched"
      cron           = var.scheduler_biyearly_admission_2nd_schedule
    }
    monthly_vacancy = {
      name           = "${var.name_prefix}-monthly-vacancy"
      args           = ["monthly_vacancy"]
      scheduler_name = "${var.name_prefix}-monthly-vacancy-sched"
      cron           = var.scheduler_monthly_vacancy_schedule
    }
    yearly_navi = {
      name           = "${var.name_prefix}-yearly-navi"
      args           = ["yearly_navi"]
      scheduler_name = "${var.name_prefix}-yearly-navi-sched"
      cron           = var.scheduler_yearly_navi_schedule
    }
    monthly_stats_compute = {
      name           = "${var.name_prefix}-monthly-stats-compute"
      args           = ["monthly_stats_compute"]
      scheduler_name = "${var.name_prefix}-monthly-stats-compute-sched"
      cron           = var.scheduler_monthly_stats_compute_schedule
    }
    wayback_backfill = {
      name           = "${var.name_prefix}-wayback-backfill"
      args           = ["wayback_backfill"]
      scheduler_name = "" # 手動 trigger only (proposal §4.5.4)
      cron           = ""
    }
  }

  # Cloud Scheduler を deploy する Job のサブセット (scheduler_name 非空のもの)
  scheduled_jobs = {
    for k, v in local.etl_jobs : k => v if v.scheduler_name != ""
  }

  # Scheduler 用 Service Account
  sa_scheduler_id    = "sa-fujisawa-scheduler"
  sa_scheduler_email = google_service_account.scheduler.email
}
