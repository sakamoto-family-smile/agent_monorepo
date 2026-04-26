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

`project_id` は env で渡し、tfvars に書かない (複数 project 切替を簡単にするため)。

```bash
cd piyolog-analytics

# 1. tfvars を準備 (project_id は env で渡すので、tfvars には書かない)
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# region / name_prefix / cloud_sql_* 等を必要なら編集

# 2. backend.tf を作る (state を GCS で管理)
cat >terraform/backend.tf <<EOF
terraform {
  backend "gcs" {
    bucket = "${PROJECT}-tfstate"
    prefix = "piyolog-analytics"
  }
}
EOF

# 3. project_id を env で渡しつつ init / plan / apply
export TF_VAR_project_id="$PROJECT"
make tf-init
make tf-plan
make tf-apply
```

**dev / prod 切替**:

```bash
# dev project
TF_VAR_project_id=my-dev-project make tf-plan

# prod project
TF_VAR_project_id=my-prod-project make tf-plan
```

同じ tfvars + backend.tf で project を切り替えられる (state は GCS bucket 名 + prefix が dev/prod で別になる前提)。

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

## CI: PR plan-only + 週次 drift 検知

`apply` 自動化は意図せぬ destroy のリスクがあるため、CI は **plan-only** + **drift 通知** に留める方針:

| 用途 | yaml | trigger |
|---|---|---|
| PR で plan を確認 | `terraform/cloudbuild-plan.yaml` | Pull request イベント |
| 週次 drift 検知 | `terraform/cloudbuild-drift.yaml` | Cloud Scheduler (cron) |

apply は引き続き手動 (`make tf-apply` をローカルから実行)。

### 1. Cloud Build SA を専用に作る (read-only)

```bash
PROJECT="your-gcp-project-id"
gcloud iam service-accounts create tf-cloud-build-sa --project=$PROJECT

SA="tf-cloud-build-sa@${PROJECT}.iam.gserviceaccount.com"
for role in \
  roles/storage.objectViewer \
  roles/cloudsql.viewer \
  roles/secretmanager.viewer \
  roles/iam.serviceAccountViewer \
  roles/artifactregistry.reader \
  roles/logging.logWriter \
; do
  gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:${SA}" --role="$role"
done

# state bucket への read 権限 (state 取得が必要なため)
gsutil iam ch serviceAccount:${SA}:objectViewer gs://${PROJECT}-tfstate
```

> apply 権限 (writer / admin) は付与しない。これにより万が一の誤発火でも実害ゼロ。

### 2. PR plan-only trigger

```bash
gcloud builds triggers create github \
  --project=$PROJECT \
  --name=piyolog-analytics-tf-plan \
  --repo-name=agent_monorepo \
  --repo-owner=sakamoto-family-smile \
  --pull-request-pattern="^main$" \
  --build-config=piyolog-analytics/terraform/cloudbuild-plan.yaml \
  --service-account="projects/${PROJECT}/serviceAccounts/${SA}" \
  --substitutions="_TF_PROJECT_ID=${PROJECT},_TF_STATE_BUCKET=${PROJECT}-tfstate" \
  --included-files="piyolog-analytics/terraform/**"
```

`--included-files` を指定して terraform/ 以下が変わった PR だけ走らせる (アプリ変更だけの PR では発火しない)。

### 3. 週次 drift 検知 trigger

```bash
# Cloud Build trigger を manual で作る
gcloud builds triggers create manual \
  --project=$PROJECT \
  --name=piyolog-analytics-tf-drift \
  --repo=https://github.com/sakamoto-family-smile/agent_monorepo \
  --repo-type=GITHUB \
  --branch=main \
  --build-config=piyolog-analytics/terraform/cloudbuild-drift.yaml \
  --service-account="projects/${PROJECT}/serviceAccounts/${SA}" \
  --substitutions="_TF_PROJECT_ID=${PROJECT},_TF_STATE_BUCKET=${PROJECT}-tfstate"

# Cloud Scheduler から週次起動 (毎週月曜 09:00 JST)
TRIGGER_ID=$(gcloud builds triggers describe piyolog-analytics-tf-drift \
  --project=$PROJECT --format='value(id)')

gcloud scheduler jobs create http piyolog-tf-drift-weekly \
  --project=$PROJECT \
  --location=us-central1 \
  --schedule="0 9 * * 1" \
  --time-zone="Asia/Tokyo" \
  --uri="https://cloudbuild.googleapis.com/v1/projects/${PROJECT}/triggers/${TRIGGER_ID}:run" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"branchName":"main"}' \
  --oauth-service-account-email="${SA}"
```

### 4. 失敗通知

Cloud Build → Pub/Sub `cloud-builds` topic を購読する小さな関数を立てて Slack に投げるのが定番。`piyolog-analytics-tf-drift` の build status が FAILURE (= drift 検知 = exit 2) のときだけ通知すれば、drift 発生時にだけ Slack が鳴る。

これで:
- **手動変更が紛れ込んだら週次で気付ける**
- **apply は自分で打つので destroy 事故も防げる**
- **Cloud Build SA は read-only なので万が一の誤発火でも実害ゼロ**

の 3 点が揃う。

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
