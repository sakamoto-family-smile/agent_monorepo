# driving-license-bot Terraform

Phase 1 最小公開（30 問のシードプールで動く LINE Bot）に必要な GCP リソースを
Terraform で管理する。`terraform destroy` で一発削除できる構成。

## 含まれるリソース

| カテゴリ | リソース |
|---|---|
| API | run / cloudbuild / artifactregistry / firestore / secretmanager / iam / iamcredentials / logging / monitoring |
| IAM | `sa-line-bot` Service Account + project-level role bindings (datastore.user / logging.logWriter / monitoring.metricWriter) |
| Firestore | `(default)` database (asia-northeast1, native mode) |
| Secret Manager | `driving-license-bot-line-channel-secret` / `-access-token` / `-line-login-channel-secret` / `-operator-line-user-ids` の 4 枠（値は手動投入）|
| Artifact Registry | `driving-license-bot` Docker repo |
| Cloud Run | `driving-license-bot-line-bot` service（image を指定したときのみ deploy） |

含まれないもの（Phase 2 以降）:

- Cloud SQL pgvector
- Vertex AI 利用承認（Marketplace 操作が必要）
- Cloud Run Job / Workflows / Scheduler（batch 用）
- Langfuse on GKE
- Cloud Monitoring alert policy（必要に応じて analytics-platform/terraform/monitoring.tf を参照）

## 前提

- gcloud CLI 認証済み（`gcloud auth login`、Project Owner 相当）
- GCP プロジェクト作成済み（例: `sakamoto-family-agent`）
- terraform >= 1.7

## 使い方

### 1. ブートストラップ（初回のみ）

tfstate バケットを作成し、必要 API を有効化します。

```bash
cd driving-license-bot
GOOGLE_CLOUD_PROJECT=sakamoto-family-agent make bootstrap
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

LINE Developers Console から取得した値を投入:

```bash
echo -n "<channel-secret>" | gcloud secrets versions add \
    driving-license-bot-line-channel-secret --data-file=-

echo -n "<access-token>" | gcloud secrets versions add \
    driving-license-bot-line-channel-access-token --data-file=-

# 運営者通知用の LINE User ID（カンマ区切り）。任意。
echo -n "Uxxxx,Uyyyy" | gcloud secrets versions add \
    driving-license-bot-operator-line-user-ids --data-file=-
```

### 5. Image を build & push

```bash
GOOGLE_CLOUD_PROJECT=sakamoto-family-agent make image-build
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

## Teardown（一発削除）

```bash
GOOGLE_CLOUD_PROJECT=sakamoto-family-agent make teardown
```

`scripts/teardown.sh` が以下を順に実行:

1. Artifact Registry の image を全削除
2. `terraform destroy`（SA / Firestore / Secret 枠 / Cloud Run / Artifact Registry repo）
3. Secret Manager secret の即時削除（destroy のスケジュール削除を待たない）

オプション:
- `PURGE_STATE=true` で tfstate バケットも削除（完全初期化）
- `gcloud projects delete <PROJECT>` で project ごと削除（最も簡単）

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

