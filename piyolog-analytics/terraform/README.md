# piyolog-analytics Terraform

B 案 Step 3 — LINE bot を Cloud Run + Cloud SQL で常時稼働させるための GCP インフラ IaC。

| カテゴリ | リソース | ファイル |
|---|---|---|
| Cloud SQL | Postgres instance + database + user (random password) | `cloud_sql.tf` |
| Secret Manager | LINE channel secret / access token / DATABASE_URL の 3 secret | `secrets.tf` |
| Service Account | `sa-piyolog` (Cloud Run service が背負う SA) + 必要 IAM bindings | `iam.tf` |
| Artifact Registry | `piyolog-analytics` Docker repo (cloudbuild.yaml の push 先) | `artifact_registry.tf` |

**管理しないもの**:
- **Cloud Run service 本体**: `scripts/deploy_cloud_run.sh` (Step B2) でデプロイ。CI/CD で頻繁に image tag が変わるため、TF state には載せない方針 (analytics-platform 側 Step 7 と同じ)
- **VPC / GKE / Langfuse**: piyolog-analytics には不要

---

## Bootstrap (初回のみ)

state 用の GCS バケットは TF 管理外で先に作る (chicken-and-egg)。

```bash
PROJECT="your-gcp-project-id"

# state bucket (analytics-platform と共有も可、prefix で分離)
gsutil mb -p "${PROJECT}" -l US "gs://${PROJECT}-tfstate" || true
gsutil versioning set on "gs://${PROJECT}-tfstate"

# 必要 API 有効化
gcloud services enable \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  --project="${PROJECT}"
```

---

## Apply 手順

```bash
cd piyolog-analytics

# 1. tfvars を準備
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
$EDITOR terraform/terraform.tfvars     # project_id を埋める

# 2. backend.tf を作る (state を GCS で管理)
cat >terraform/backend.tf <<EOF
terraform {
  backend "gcs" {
    bucket = "${PROJECT}-tfstate"
    prefix = "piyolog-analytics"
  }
}
EOF

# 3. init / plan / apply
make tf-init
make tf-plan
make tf-apply
```

---

## LINE secrets 投入

`create_line_secret_versions=false` (default) なので、LINE Developers Console から取得した値を手動で投入:

```bash
# LINE Developers Console > Messaging API から取得した値を投入
echo -n "$LINE_CHANNEL_SECRET" | \
  gcloud secrets versions add piyolog-line-channel-secret --data-file=- --project=$PROJECT

echo -n "$LINE_CHANNEL_ACCESS_TOKEN" | \
  gcloud secrets versions add piyolog-line-channel-access-token --data-file=- --project=$PROJECT
```

`DATABASE_URL` は TF が組み立てて投入するので手動操作不要。

---

## Deploy 連携

`outputs.tf` の `env_for_deploy` map から `scripts/deploy_cloud_run.sh` 用の env を取り出せる:

```bash
make tf-output-env             # → ../.env.deploy
set -a; source .env.deploy; set +a

# 残りの env (LINE 関連 + 家族 userId) を環境変数で足してから deploy
PIYOLOG_FAMILY_USER_IDS="Uxxx,Uyyy" \
PIYOLOG_IMAGE_TAG=latest \
make deploy-cloud-run
```

---

## 既存リソースの import

手動で先に作ったリソースがあれば取り込み可能:

```bash
# Cloud SQL instance
terraform import google_sql_database_instance.piyolog ${PROJECT}/${INSTANCE_NAME}

# Secret Manager secret
terraform import google_secret_manager_secret.line_channel_secret \
  projects/${PROJECT}/secrets/piyolog-line-channel-secret

# Service account
terraform import google_service_account.piyolog \
  projects/${PROJECT}/serviceAccounts/sa-piyolog@${PROJECT}.iam.gserviceaccount.com
```

---

## 破壊的変更

- **Cloud SQL**: `cloud_sql_deletion_protection = true` (default) で `terraform destroy` 時にエラーになる。dev では tfvars で false にする
- **Secret Manager**: secret container の destroy は version も含めて消える。LINE 側に保存があれば再投入可能
- **DATABASE_URL の version 更新**: `random_password.cloud_sql_db_password` が変わると `database_url` も変わり、新しい version が投入される。Cloud Run service は `:latest` を参照するので自動追従するが、既存接続は切れる (再起動が必要)

---

## トラブルシュート

| 症状 | 対処 |
|---|---|
| `Cloud SQL Admin API not enabled` | `gcloud services enable sqladmin.googleapis.com` |
| `Secret already exists` | `terraform import google_secret_manager_secret.X projects/.../secrets/X` |
| `Permission denied on Cloud SQL` | 操作者 IAM に `roles/cloudsql.admin` を付与 |
| Cloud Run service が deploy できない (deploy_cloud_run.sh が失敗) | `make tf-output env_for_deploy` の値を渡しているか確認 |
