# driving-license-bot Terraform

Phase 1 最小公開（30 問のシードプールで動く LINE Bot）+ Phase 2-A の Cloud SQL pgvector
基盤までを Terraform で管理する。`terraform destroy` で一発削除できる構成。

## 含まれるリソース

| カテゴリ | リソース |
|---|---|
| API | run / cloudbuild / artifactregistry / firestore / secretmanager / iam / iamcredentials / logging / monitoring / sqladmin / **aiplatform / workflows / cloudscheduler** |
| IAM | `sa-line-bot` (datastore.user / logging.logWriter / monitoring.metricWriter) + **`sa-batch` (aiplatform.user / cloudsql.client / datastore.user / logging.logWriter / monitoring.metricWriter / 4 secret accessor) + `sa-workflow` (run.invoker / logging.logWriter / actAs sa-batch) + `sa-scheduler` (workflows.invoker)** |
| Firestore | `(default)` database (asia-northeast1, native mode) |
| Secret Manager | `driving-license-bot-line-channel-secret` / `-access-token` / `-line-login-channel-secret` / `-operator-line-user-ids` の 4 枠（値は手動投入）+ `-cloudsql-password` の 1 枠（terraform が `random_password` で投入） |
| Artifact Registry | `driving-license-bot` Docker repo |
| Cloud Run | `driving-license-bot-line-bot` service / **`driving-license-bot-admin-ui` service (IAP 直接適用)** / `driving-license-bot-batch` Cloud Run Job (image を指定したときのみ deploy) |
| Cloud SQL | `driving-license-bot-pg` (Postgres 15, db-f1-micro, asia-northeast1) + `question_bank` database + `app` user |
| Workflows | `driving-license-bot-generation-pipeline` (workflows/generation_pipeline.yaml を埋め込み) |
| Scheduler | `driving-license-bot-batch-nightly` (cron 02:00 JST) |
| **IAP** | **`google_iap_web_cloud_run_service_iam_member` で `review_admin_allowed_emails` に `roles/iap.httpsResourceAccessor` 付与** |
| **Backup bucket** | **`<PROJECT>-driving-license-bot-backups` (versioning ON, lifecycle 90 日)** + Firestore service agent / Cloud SQL SA への objectAdmin 付与 |

含まれないもの（次フェーズ以降）:

- 重複検査スキーマ作成（PR A2 の `scripts/init_question_bank_schema.py` で別途投入）
- Vertex AI Claude Marketplace 承認（手動。承認前は `agent_llm_provider=gemini` で動作）
- **OAuth consent screen の configure**（Console で 1 度だけ手動、IAP 利用時必須）
- Langfuse on GKE
- Cloud Monitoring alert policy / 運営者通知 (Phase 2-B3)

## 前提

- gcloud CLI 認証済み（`gcloud auth login`、Project Owner 相当）
- GCP プロジェクト作成済み（例: `sakamoto-family-agent`）
- terraform >= 1.7

## 使い方

### 1. ブートストラップ（初回のみ）

tfstate バケットを作成し、必要 API を有効化します。
`GOOGLE_CLOUD_PROJECT` は `gcloud config` から自動取得されるので env 指定は不要。

```bash
cd driving-license-bot
make show-project   # 自動取得値を確認
make bootstrap
```

別 project を一時的に使う場合は env で override:

```bash
GOOGLE_CLOUD_PROJECT=other-project make bootstrap
```

このコマンドで:
- `gs://${PROJECT}-driving-license-bot-tfstate` バケットを作成（versioning 有効）
- `terraform/backend.tf` を自動生成
- base API（serviceusage / cloudresourcemanager / iam）を有効化
- `terraform/terraform.tfvars` をサンプルから生成（編集前提）

### 2. tfvars を編集

```bash
$EDITOR terraform/terraform.tfvars
```

最低限 `project_id` のみ設定すれば動きます（既定値が `sakamoto-family-agent`）。

### 3. 基盤を作る（image なしで apply）

```bash
make tf-init
make tf-plan
make tf-apply
```

これで:
- 必要 API がすべて有効化
- `sa-line-bot` SA + role 付与
- Firestore (default) database
- Secret Manager 4 枠（値はまだ空）
- Artifact Registry repo

が揃います。Cloud Run service はまだ deploy されません（image 未指定のため）。

### 4. Secret に値を投入

```bash
cp .env.secrets.example .env.secrets
$EDITOR .env.secrets   # 値を埋める（gitignored）
make secrets-push
```

push スクリプトは末尾改行混入を防ぎ、bytes 表示で目視確認できます。

> teardown-app では Secret 値は消えないので、一度投入すれば後の deploy cycle
> で再投入不要。LINE 側で token rotation した時だけ `.env.secrets` 更新 +
> 再 `make secrets-push`。

### 5. Image を build & push

```bash
make image-build
```

push 完了後、`asia-northeast1-docker.pkg.dev/${PROJECT}/driving-license-bot/line-bot:latest` が利用可能になります。

### 6. tfvars を更新して Cloud Run service を deploy

`terraform.tfvars` の `line_bot_image` をコメント解除して埋める:

```hcl
line_bot_image = "asia-northeast1-docker.pkg.dev/sakamoto-family-agent/driving-license-bot/line-bot:latest"
```

再 apply:

```bash
make tf-apply
```

### 7. Webhook URL を LINE Console に登録

```bash
cd terraform && terraform output line_bot_webhook_url
# 例: https://driving-license-bot-line-bot-XXXX.a.run.app/webhook
```

これを LINE Developers Console の Webhook URL に貼り付けて Verify。

## Teardown（2 モード）

| モード | 残るもの | CI plan | 用途 |
|---|---|---|---|
| `make teardown-app` | WIF / tfstate / API 有効化 / sa-terraform-plan | ✅ 動作継続 | 課金停止したいが CI は維持 |
| `make teardown` | （ほぼ）何も残らない | ❌ 再 bootstrap 必要 | 完全初期化 |

### `make teardown-app`（推奨デフォルト）

```bash
make teardown-app
```

削除されるもの:
- Cloud Run service (`line-bot-service`)
- Firestore database
- Artifact Registry repo + image
- `sa-line-bot` SA + IAM 3 件
- **Cloud SQL instance (`driving-license-bot-pg`)** ← 月 ~$10 を停止するため

残るもの:
- WIF / `sa-terraform-plan` / tfstate バケット / 有効化済み API（実質無料）
- **Secret Manager 5 secrets（値ごと）** ← LINE 4 + cloudsql-password
  - cloudsql-password 自体は次回 apply 時に random_password で再生成され Secret Manager にも上書き
  - したがって teardown-app → apply 後に Cloud SQL 内のデータは失われる（重複検査用 DB のため再生成可）

→ `Terraform plan / driving-license-bot` ジョブは引き続き動作。
→ 再展開する場合は tfvars に `line_bot_image` を埋めて `make tf-apply`。
→ LINE secret は前回値が再利用される。LINE 側で token rotation した時だけ
  `.env.secrets` を更新して `make secrets-push`。
→ Cloud SQL は再生成されるため `make cloudsql-init`（PR A2 で追加予定）でスキーマを
  再投入し、必要なら Question Bank への問題再 import も実施する。

### `make teardown`（完全削除）

```bash
make teardown
```

`scripts/teardown.sh` が以下を順に実行:

1. Artifact Registry の image を全削除
2. `terraform destroy`（**WIF 含む全リソース**）
3. Secret Manager secret の即時削除

オプション:
- `PURGE_STATE=true` で tfstate バケットも削除（完全初期化）
- `gcloud projects delete <PROJECT>` で project ごと削除（最も簡単）

⚠️ teardown 後は `make bootstrap` から再実施し、GitHub Variables も再登録が必要。

## 安全装置

| 変数 | 既定 | 説明 |
|---|---|---|
| `force_destroy` | `true` | dev/PoC 想定で `true`。本番化時は `false` |
| `deletion_protection` | `false` | 同上。Firestore database の delete 防護 |

本番運用に入るタイミングで `terraform.tfvars` を `force_destroy = false`、
`deletion_protection = true` に変更すること（重要）。

## Drift 検知（任意）

CI で `terraform plan -detailed-exitcode` を回せば手動変更を検知できます。
piyolog-analytics の同パターン参照。

---

## CI で `terraform plan` を回す（Workload Identity Federation）

GitHub Actions から GCP に **長期 SA キーを使わずに** 短期トークンで認証する
構成を Terraform で管理しています。`enable_wif=true` で apply すれば、
PR ごとに自動で plan が走ります。

### 一回限りのセットアップ

#### 1. 基盤 + WIF を一緒に apply

`terraform.tfvars` を編集:

```hcl
enable_wif     = true
github_repo    = "sakamoto-family-smile/agent_monorepo"
tfstate_bucket = "sakamoto-family-agent-driving-license-bot-tfstate"
```

apply:

```bash
make tf-apply
```

これで以下が作られる:

- WIF Pool: `github-actions-pool`
- WIF Provider: `github`（GitHub OIDC、`assertion.repository == "<owner>/<repo>"` で repo フィルタ）
- `sa-terraform-plan@<project>.iam.gserviceaccount.com`（read-only）
- WIF binding: 上記 GitHub repo が SA を impersonate 可能

#### 2. GitHub repo に Variables を登録

`terraform output wif_setup_summary` で値が出ます:

```bash
cd terraform && terraform output -json wif_setup_summary
```

出力例:

```json
{
  "WIF_PROVIDER":   "projects/123456789/locations/global/workloadIdentityPools/github-actions-pool/providers/github",
  "TF_PLAN_SA":     "sa-terraform-plan@sakamoto-family-agent.iam.gserviceaccount.com",
  "TFSTATE_BUCKET": "sakamoto-family-agent-driving-license-bot-tfstate",
  "GCP_PROJECT_ID": "sakamoto-family-agent"
}
```

GitHub の `Settings > Secrets and variables > Actions > Variables` で
**4 つの Variables** として登録（Secrets ではなく Variables。値は機密ではない）:

| Variable name | 値 |
|---|---|
| `WIF_PROVIDER` | `projects/.../providers/github` |
| `TF_PLAN_SA` | `sa-terraform-plan@...` |
| `TFSTATE_BUCKET` | tfstate バケット名 |
| `GCP_PROJECT_ID` | `sakamoto-family-agent` |

#### 3. 動作確認

driving-license-bot/terraform/ 配下に何か変更を加えた PR を立てると、
**`Terraform plan / driving-license-bot`** ジョブが起動して plan 結果が PR に
コメントされます。

vars が未設定 / 空ならジョブごとスキップ（PR は通る）。

### セキュリティ上の注意

- `attribute_condition` で **特定の repo のみ** が認証できるよう制限
- fork からの PR は OIDC token の `assertion.repository` が一致しないため弾かれる
- `sa-terraform-plan` は **read-only**（`roles/viewer` + `secretmanager.viewer` +
  `iam.serviceAccountViewer` + tfstate bucket の `objectViewer`）
- write 権限は持たないため、悪意ある PR でも resource 作成・削除は不可能
- `terraform apply` は引き続き手元の `make tf-apply` でのみ実行する運用

### 撤去

```bash
# tfvars を編集して enable_wif = false に
make tf-apply
```

または完全に消したいなら `make teardown`。
