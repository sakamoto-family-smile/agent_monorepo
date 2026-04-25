# analytics-platform Terraform

Phase 5 GCP 運用基盤の IaC。本ディレクトリで管理するもの:

| カテゴリ | リソース | ファイル |
|---|---|---|
| Step 3 | GCS bucket × 3 (raw / payloads / dead_letter) + lifecycle | `gcs.tf` |
| Step 1 | Artifact Registry Docker repo | `artifact_registry.tf` |
| Step 4 | BigQuery dataset × 3 (raw / staging / marts) + external table | `bigquery.tf` |
| Step 9 | Cloud Monitoring alert policy × 3 + email notification channel | `monitoring.tf` |
| 共通 | Service Account × 4 + IAM bindings | `iam.tf` |

管理しないもの (現時点):

- Cloud Run Job 本体: 既存の `gcloud run jobs deploy` でデプロイ (Step 7、image SHA を CI/CD から流し込みたいため)
- Cloud Workflows / Scheduler: `scripts/deploy_orchestration.sh` で gcloud 経由 (Step 8)
- VPC / GKE / Langfuse: Step 2 として後続で別 module 化予定

> **方針**: Step 1-3 (静的なデータ基盤 + IAM) は Terraform、Step 7-8 (CI/CD で頻繁に更新するアプリ寄り) は gcloud script、と棲み分け。

---

## Bootstrap (初回のみ)

state を保存する GCS バケットは Terraform 管理外で先に作る (chicken-and-egg)。

```bash
PROJECT="your-gcp-project-id"
LOCATION="US"

# state bucket
gsutil mb -p "${PROJECT}" -l "${LOCATION}" "gs://${PROJECT}-tfstate"
gsutil versioning set on "gs://${PROJECT}-tfstate"

# 必要 API 有効化 (まとめて)
gcloud services enable \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  bigquery.googleapis.com \
  run.googleapis.com \
  workflows.googleapis.com \
  cloudscheduler.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  --project="${PROJECT}"
```

---

## Apply 手順

ルートの `Makefile` に `tf-*` ターゲットがあるので、リポジトリルートから呼ぶのが基本:

```bash
cd analytics-platform

# 1. tfvars を準備
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
$EDITOR terraform/terraform.tfvars     # project_id を埋める

# 2. backend.tf でバケット名を指定
cat >terraform/backend.tf <<'EOF'
terraform {
  backend "gcs" {
    bucket = "your-gcp-project-id-tfstate"
    prefix = "analytics-platform"
  }
}
EOF

# 3. init / plan / apply
make tf-init       # ≡ cd terraform && terraform init
make tf-plan       # ≡ terraform plan -out=tfplan
make tf-apply      # ≡ terraform apply tfplan

# 4. 出力された env を .env.gcp に流し込む
make tf-output-env  # → analytics-platform/.env.gcp
```

直接 `terraform` を呼びたい場合:

```bash
cd analytics-platform/terraform
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

**追加の make ターゲット**:

| target | 内容 |
|---|---|
| `make tf-fmt` | `terraform fmt -recursive` (auto-fix) |
| `make tf-fmt-check` | `terraform fmt -check -recursive` (CI 用) |
| `make tf-validate` | `terraform init -backend=false && terraform validate` (認証不要) |

> **ヒント**: 初回は `create_bq_external_table = false` にして apply →
> consumer が JSONL を GCS に流し始めたあとで `true` に変えて再 apply するのが安全。
> Hive autodetect は GCS 上に少なくとも 1 ファイルないとスキーマ推論に失敗する。

---

## terraform output の使い方

`outputs.tf` で `env_for_dotenv` という map を出すので、`.env` に流し込める:

```bash
# 個別の値
cd terraform
terraform output -raw raw_bucket
terraform output -raw sa_uploader_email

# .env 形式で一括出力 (Makefile 経由が楽)
cd ..
make tf-output-env                          # → analytics-platform/.env.gcp
make tf-output-env TF_ENV_FILE=.env.dev     # 出力先を変えたいとき

# consumer / dbt / workflow に env を読み込ませる
set -a
source .env.gcp
set +a
make deploy-orchestration
```

---

## Step 9 Cloud Monitoring アラート

`monitoring.tf` で 3 個の alert policy を作成 (詳細は §3.5.2 of root README)。

| policy | 検知 | しきい値 | 重要度 |
|---|---|---|---|
| `workflow_failed` | Cloud Workflows execution が FAILED | 5 分間に 1 件以上 | high |
| `dbt_job_failed` | Cloud Run Job が failed で完了 | 5 分間に 1 件以上 | high |
| `dbt_job_slow` | Cloud Run Job duration > `dbt_job_max_duration_seconds` (default 30 分) | 1 分継続 | medium |

通知は email channel (`notification_email` 必須)。`enable_alerts = false` で全部スキップ可能。

```bash
# 通知先 email を terraform.tfvars に設定 → apply
echo 'notification_email = "alerts@example.com"' >> terraform.tfvars
make tf-plan
make tf-apply
```

Slack に飛ばしたいときは Step 8 の Workflow 内 webhook (`ANALYTICS_SLACK_WEBHOOK_URL`) を使うか、Pub/Sub → Cloud Run の通知ブリッジを別途立てる。

---

## drift 検知

```bash
terraform plan -detailed-exitcode
# exit 0: no changes
# exit 1: error
# exit 2: drift detected
```

CI に組み込んで weekly で回すと、手動変更が混入したときに検知できる。

---

## 破壊的変更について

- **GCS バケット**: `force_destroy = false` (既定) のため、空でないと `terraform destroy` できない。本番では `false` のまま運用する。
- **BQ external table**: `deletion_protection = false` (external なので削除しても GCS データは無傷)。ただし dataset は default の `true`。
- **Service Account**: 削除すると Cloud Run Job / Workflows / Scheduler が即座に動作不能になる。`terraform destroy` は plan の差分を必ず確認する。

---

## 既存リソースを Terraform に取り込む (import)

`scripts/gcp_bootstrap.sh` で先に作ったリソースがあれば、`terraform import` で state に取り込める:

```bash
# BigQuery dataset の例
terraform import google_bigquery_dataset.raw projects/${PROJECT}/datasets/analytics_raw

# GCS bucket の例
terraform import google_storage_bucket.raw ${BUCKET}
```

import 後 `terraform plan` で差分が出る場合は、`tfvars` の値を実体に合わせて調整する。

---

## トラブルシュート

| 症状 | 対処 |
|---|---|
| `Permission denied on bucket` | 操作者の SA に `roles/storage.admin` がついているか確認 |
| `BQ dataset already exists` | `terraform import` で既存 dataset を state に取り込む |
| `Hive partitioning autodetect failed` | GCS にまだ JSONL が無い → `create_bq_external_table = false` で apply |
| `Service account not found` | apply 直後の eventual consistency。数秒待って再 apply |
