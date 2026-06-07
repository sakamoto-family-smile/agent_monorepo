# stock-analysis-agent terraform (PROPOSAL-0011 P1)

`stock-analysis-line` Cloud Run Service を `sakamomo-family-agent` に配備する。
MVP は **ephemeral SQLite**（永続化は Phase 2 で shared Cloud SQL）。Cloud SQL /
Vertex AI は使わない（LLM は Anthropic OAuth token 経由の claude-agent-sdk）。

作成リソース:
- Cloud Run Service `stock-analysis-line`（`var.image` が空なら作らない）
- Service Account `sa-stock-analysis-line` + Logging/Artifact Reader
- Secret Manager 4 件（**値は手動投入**）:
  - `stock-analysis-line-line-channel-secret`
  - `stock-analysis-line-line-channel-access-token`
  - `stock-analysis-line-claude-code-oauth-token`
  - `stock-analysis-line-brave-api-key`
- Artifact Registry repo `stock-analysis-line`

## デプロイ手順（chicken-and-egg: 基盤 → image → service）

### 0. 準備

```bash
cd stock-analysis-agent/terraform
cp terraform.tfvars.example terraform.tfvars
# project_id / 各種スペックを確認（image は空のまま）
terraform init
```

### 1. 基盤だけ作る（image="" のまま）

```bash
terraform apply   # SA / IAM / secrets(空) / Artifact Registry を作成
```

### 2. Secret 値を投入

LINE Developers Console で Messaging API チャネルを作成 → 値を取得して投入:

```bash
gcloud secrets versions add stock-analysis-line-line-channel-secret --data-file=- <<<'＜channel secret＞'
gcloud secrets versions add stock-analysis-line-line-channel-access-token --data-file=- <<<'＜channel access token＞'

# Claude OAuth token（`claude setup-token` で取得、有効期限 1 年）
gcloud secrets versions add stock-analysis-line-claude-code-oauth-token --data-file=- <<<'＜oauth token＞'

# Brave Search API key
gcloud secrets versions add stock-analysis-line-brave-api-key --data-file=- <<<'＜brave api key＞'
```

> 値はシェル履歴に残さないよう注意（`--data-file=` でファイル経由が安全）。

### 3. image を build & push

```bash
# リポジトリルートから
gcloud builds submit \
  --config=stock-analysis-agent/cloudbuild.yaml \
  --ignore-file=stock-analysis-agent/cloudbuild.gcloudignore \
  --substitutions=_SHA=$(git rev-parse --short=7 HEAD) \
  .
```

### 4. image を指定して Cloud Run Service を作る

```bash
# terraform.tfvars の image を push した tag に更新
#   image = "asia-northeast1-docker.pkg.dev/sakamomo-family-agent/stock-analysis-line/stock-analysis-line:<sha>"
terraform apply
terraform output service_url   # → https://stock-analysis-line-xxxx-an.a.run.app
```

### 5. PUBLIC_BASE_URL を反映（チャート画像 / 全文 DL に必要）

```bash
# terraform.tfvars の public_base_url に service_url を設定して再 apply
#   public_base_url = "https://stock-analysis-line-xxxx-an.a.run.app"
terraform apply
```

> `public_base_url` 未設定でも要約 Flex は届くが、チャート画像と全文 .md リンクは出ない。

### 6. LINE Webhook 登録 + allow-list

- LINE Developers Console > Messaging API > Webhook URL に
  `<service_url>/api/line/webhook` を登録し、Webhook 利用を ON。
- `terraform.tfvars` の `family_user_ids` に家族の LINE userId（`U...`）を CSV で設定 →
  `terraform apply`（**本番では必須**。未設定だと誰でも Opus 分析を叩ける）。

### 7. 疎通

LINE で `ヘルプ` → コマンド一覧、`分析 トヨタ` → ack 後に要約 Flex + チャート画像 +
「📄 全文(.md)」ボタンが届けば OK。

## 更新（image 入れ替え）

```bash
gcloud builds submit --config=stock-analysis-agent/cloudbuild.yaml \
  --ignore-file=stock-analysis-agent/cloudbuild.gcloudignore \
  --substitutions=_SHA=$(git rev-parse --short=7 HEAD) .
gcloud run services update stock-analysis-line --region=asia-northeast1 \
  --image=asia-northeast1-docker.pkg.dev/sakamomo-family-agent/stock-analysis-line/stock-analysis-line:<sha>
```

terraform は `image` の drift を無視する（`ignore_changes`）ので、上記 `gcloud run
services update` 直叩きで OK。
