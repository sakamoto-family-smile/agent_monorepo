# Cloud Tasks queue + invoker SA (PROPOSAL-0011 P3-A)。
#
# webhook (stock-analysis-line) が分析タスクをこの queue に enqueue し、
# Cloud Tasks が OIDC 認証付き HTTP POST で worker (stock-analysis-worker) を叩く。
# queue が流量制御 (max_concurrent_dispatches) + リトライ + 永続化を担う。

data "google_project" "this" {
  project_id = var.project_id
}

resource "google_cloud_tasks_queue" "analysis" {
  project  = var.project_id
  location = var.region
  name     = var.tasks_queue_name

  rate_limits {
    max_concurrent_dispatches = var.tasks_max_concurrent_dispatches
    max_dispatches_per_second = var.tasks_max_dispatches_per_second
  }

  retry_config {
    max_attempts       = var.tasks_max_attempts
    min_backoff        = "5s"
    max_backoff        = "300s"
    max_doublings      = 4
    max_retry_duration = "1800s"
  }

  depends_on = [google_project_service.cloudtasks]
}

# Cloud Tasks が worker を叩く際の OIDC identity (worker が email を検証)。
# 実権限は持たせない (worker は public Cloud Run、app 内でトークン検証する)。
resource "google_service_account" "tasks_invoker" {
  account_id   = local.sa_tasks_invoker_name
  display_name = "stock-analysis Cloud Tasks OIDC invoker"

  depends_on = [google_project_service.iam]
}

# webhook SA が task 作成時に invoker SA を oidc_token に設定できるようにする。
resource "google_service_account_iam_member" "webhook_uses_invoker" {
  service_account_id = google_service_account.tasks_invoker.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.service.email}"
}

# Cloud Tasks サービスエージェントが invoker SA の OIDC token を発行できるようにする。
resource "google_service_account_iam_member" "cloudtasks_token_creator" {
  service_account_id = google_service_account.tasks_invoker.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-cloudtasks.iam.gserviceaccount.com"
}

# webhook SA が queue に enqueue できるようにする。
resource "google_project_iam_member" "service_tasks_enqueuer" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.service.email}"
}
