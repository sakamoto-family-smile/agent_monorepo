# Workload Identity Federation: GitHub Actions が GCP に短期トークンで認証する。
# 長期 SA キーを GitHub Secrets に置かない構成（推奨ベストプラクティス）。
#
# `enable_wif=true` で apply すると、後段の CI（pr-tests.yml の
# `Terraform plan / driving-license-bot` ジョブ）が `terraform plan` を
# 自動実行できるようになる。
#
# 段階的セットアップ（terraform/README.md にも同手順）:
#   1. enable_wif=false の状態で初回 apply（基盤を作る）
#   2. enable_wif=true に変更して apply（WIF を作る）
#   3. `terraform output wif_*` で provider 名 / SA email を取り、
#      GitHub repo の Variables に WIF_PROVIDER / TF_PLAN_SA / TFSTATE_BUCKET を登録
#   4. 次の PR から CI が plan を回す

# ---- WIF Pool ----

resource "google_iam_workload_identity_pool" "github" {
  count = var.enable_wif ? 1 : 0

  workload_identity_pool_id = "github-actions-pool"
  display_name              = "GitHub Actions Pool"
  description               = "OIDC trust for github.com/${var.github_repo}"

  depends_on = [google_project_service.iam]
}

# ---- WIF Provider (GitHub OIDC) ----

resource "google_iam_workload_identity_pool_provider" "github" {
  count = var.enable_wif ? 1 : 0

  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # 重要: repository でフィルタする（他リポジトリからの不正な OIDC を弾く）
  attribute_condition = "assertion.repository == \"${var.github_repo}\""
}

# ---- Service Account: terraform plan 専用（read-only） ----

resource "google_service_account" "tf_plan" {
  count = var.enable_wif ? 1 : 0

  project      = var.project_id
  account_id   = "sa-terraform-plan"
  display_name = "Terraform plan via GitHub Actions WIF"
  description  = "Read-only SA used by CI to run `terraform plan`. No write access."

  depends_on = [google_project_service.iam]
}

# project-level: viewer ロール（Cloud Run / Firestore / Secret 等を読む）
resource "google_project_iam_member" "tf_plan_viewer" {
  count = var.enable_wif ? 1 : 0

  project = var.project_id
  role    = "roles/viewer"
  member  = "serviceAccount:${google_service_account.tf_plan[0].email}"
}

# Service Account 自身のメタデータ参照
resource "google_project_iam_member" "tf_plan_sa_viewer" {
  count = var.enable_wif ? 1 : 0

  project = var.project_id
  role    = "roles/iam.serviceAccountViewer"
  member  = "serviceAccount:${google_service_account.tf_plan[0].email}"
}

# Secret Manager は roles/viewer に含まれず別途必要
resource "google_project_iam_member" "tf_plan_secret_viewer" {
  count = var.enable_wif ? 1 : 0

  project = var.project_id
  role    = "roles/secretmanager.viewer"
  member  = "serviceAccount:${google_service_account.tf_plan[0].email}"
}

# tfstate バケット (read のみ)
resource "google_storage_bucket_iam_member" "tf_plan_state_viewer" {
  count = var.enable_wif ? 1 : 0

  bucket = var.tfstate_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.tf_plan[0].email}"
}

# `terraform plan` は管理リソース (google_*_iam_member 等) の現状取得のため
# `*.getIamPolicy` permissions が必要。`roles/iam.securityReviewer` は
# IAM policy の **read のみ** なので read-only 制約は守られる。
resource "google_project_iam_member" "tf_plan_security_reviewer" {
  count = var.enable_wif ? 1 : 0

  project = var.project_id
  role    = "roles/iam.securityReviewer"
  member  = "serviceAccount:${google_service_account.tf_plan[0].email}"
}

# WIF binding: GitHub repo が SA を impersonate できる
resource "google_service_account_iam_member" "tf_plan_wif" {
  count = var.enable_wif ? 1 : 0

  service_account_id = google_service_account.tf_plan[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.repository/${var.github_repo}"
}
