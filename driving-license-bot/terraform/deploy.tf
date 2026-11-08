# main へのマージで本番へ自動デプロイする SA (.github/workflows/deploy.yml が使う)。
#
# WIF の Pool / Provider はこの terraform (wif.tf) にあるので、他サービスの分もここで持つ。
# deploy.yml がするのは「image を build → Artifact Registry へ push → Cloud Run の image を差し替える」だけ。
# env・secret・SA などの設定は各サービスの terraform / デプロイスクリプトのまま触らない。
#
# 権限は最小限:
#   - 借りられるのは main ブランチ上の deploy.yml だけ (PR ブランチや他のワークフローからは借りられない)
#   - push できるのは対象サービスの Artifact Registry リポジトリだけ
#   - 更新できるのは対象の Cloud Run service / job だけ
#   - actAs できるのは対象サービスの実行 SA だけ
#
# 対象を増やすときは local.deploy_targets と deploy.yml の SERVICES を両方直す。

locals {
  deploy_targets = {
    piyolog-analytics = {
      repository = "piyolog-analytics"
      services   = { "piyolog-analytics" = "sa-piyolog" }
      jobs       = {}
    }
    driving-license-bot = {
      repository = "driving-license-bot"
      services = {
        "driving-license-bot-line-bot" = "sa-line-bot"
        "driving-license-bot-admin-ui" = "sa-admin-ui"
      }
      jobs = { "driving-license-bot-batch" = "sa-batch" }
    }
    fujisawa-info-bot = {
      repository = "fujisawa-info-bot"
      services   = { "fujisawa-info-bot" = "sa-fujisawa-info-bot" }
      jobs       = {}
    }
  }

  deploy_repositories = toset([for t in local.deploy_targets : t.repository])
  deploy_services     = merge([for t in local.deploy_targets : t.services]...)
  deploy_jobs         = merge([for t in local.deploy_targets : t.jobs]...)
  deploy_runtime_sas  = toset(concat(values(local.deploy_services), values(local.deploy_jobs)))

  deploy_workflow_ref = "${var.github_repo}/.github/workflows/deploy.yml@refs/heads/main"
}

resource "google_service_account" "deployer" {
  count = var.enable_wif ? 1 : 0

  project      = var.project_id
  account_id   = "sa-deployer"
  display_name = "Deploy to Cloud Run via GitHub Actions WIF"
  description  = "Used only by deploy.yml on main. Pushes images and swaps the Cloud Run image."

  depends_on = [google_project_service.iam]
}

# main 上の deploy.yml だけが借りられる
resource "google_service_account_iam_member" "deployer_wif" {
  count = var.enable_wif ? 1 : 0

  service_account_id = google_service_account.deployer[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.job_workflow_ref/${local.deploy_workflow_ref}"
}

resource "google_artifact_registry_repository_iam_member" "deployer_push" {
  for_each = var.enable_wif ? local.deploy_repositories : toset([])

  project    = var.project_id
  location   = var.region
  repository = each.key
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deployer[0].email}"
}

resource "google_cloud_run_v2_service_iam_member" "deployer_service" {
  for_each = var.enable_wif ? local.deploy_services : {}

  project  = var.project_id
  location = var.region
  name     = each.key
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deployer[0].email}"
}

resource "google_cloud_run_v2_job_iam_member" "deployer_job" {
  for_each = var.enable_wif ? local.deploy_jobs : {}

  project  = var.project_id
  location = var.region
  name     = each.key
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deployer[0].email}"
}

# 更新の完了待ち (operations.get) と、ロールバック先のリビジョンを調べるため
resource "google_project_iam_member" "deployer_run_viewer" {
  count = var.enable_wif ? 1 : 0

  project = var.project_id
  role    = "roles/run.viewer"
  member  = "serviceAccount:${google_service_account.deployer[0].email}"
}

# 新しいリビジョンを実行 SA で動かすための actAs
resource "google_service_account_iam_member" "deployer_act_as" {
  for_each = var.enable_wif ? local.deploy_runtime_sas : toset([])

  service_account_id = "projects/${var.project_id}/serviceAccounts/${each.key}@${var.project_id}.iam.gserviceaccount.com"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer[0].email}"
}
