# Phase 1 最小デプロイ手順

driving-license-bot を **30 問のシードプール** だけで動く LINE Bot として
GCP 上で公開する手順。すべて Terraform 駆動で、`make teardown` で一発削除可能。

> 詳細な Terraform 仕様は [terraform/README.md](../terraform/README.md) を参照。
> Phase 2 以降の Cloud SQL / Vertex AI / batch / workflows は本ドキュメントの対象外。

---

## 全体像

```
1. GCP プロジェクト準備 (sakamoto-family-agent)
        ▼
2. ブートストラップ (tfstate バケット + base API)        ← scripts/bootstrap_gcp.sh
        ▼
3. Terraform で基盤作成 (SA / Firestore / Secret 枠 / Artifact Registry)
        ▼
4. LINE Channel 作成 + Secret に値投入
        ▼
5. Cloud Build で image を build & push
        ▼
6. Terraform で Cloud Run service deploy
        ▼
7. LINE Webhook URL を登録 + 動作確認
```

teardown:

```
make teardown   # → image purge → terraform destroy → secret 削除
```

---

## 1. GCP プロジェクト準備

すでに `sakamoto-family-agent` を作成済み前提。billing が紐づいているか確認:

```bash
gcloud billing projects describe sakamoto-family-agent
```

`gcloud auth login` でオーナー相当のアカウントでログイン:

```bash
gcloud auth login
gcloud config set project sakamoto-family-agent
```

---

## 2. ブートストラップ

`GOOGLE_CLOUD_PROJECT` は `gcloud config` から自動取得されるので env 指定は不要です。

```bash
cd driving-license-bot
make show-project   # 自動取得された値を確認
make bootstrap
```

別 project を一時的に使う場合は env で override:

```bash
GOOGLE_CLOUD_PROJECT=other-project make bootstrap
```

このコマンドが:
- `gs://sakamoto-family-agent-driving-license-bot-tfstate` バケット作成（versioning 有効）
- `terraform/backend.tf` 自動生成
- 必須 base API（serviceusage / cloudresourcemanager / iam）有効化
- `terraform/terraform.tfvars` をサンプルから生成

完了後、`terraform/terraform.tfvars` を確認:

```hcl
project_id  = "sakamoto-family-agent"
region      = "asia-northeast1"
name_prefix = "driving-license-bot"
# line_bot_image = ""  ← 初回はこのまま空に
force_destroy        = true   # dev/PoC 設定。本番化時に false
deletion_protection  = false  # 同上
```

---

## 3. Terraform で基盤作成（image なしで apply）

```bash
make tf-init
make tf-plan
make tf-apply
```

これで以下が作られる:

| 種別 | リソース |
|---|---|
| API 有効化 | run / cloudbuild / artifactregistry / firestore / secretmanager / iam / iamcredentials / logging / monitoring |
| SA | `sa-line-bot@sakamoto-family-agent.iam.gserviceaccount.com` |
| Firestore | `(default)` database (asia-northeast1, native) |
| Secret 枠 | 4 件（値はまだ空） |
| Artifact Registry | `driving-license-bot` Docker repo |

Cloud Run service はまだ作られない（image 未指定のため）。

---

## 4. LINE Channel 作成 + Secret 投入

[SETUP.md §2](./SETUP.md#2-line-messaging-api-bot-チャネル作成) に従って LINE Messaging API channel を作成し、以下を控える:

- Channel secret
- Channel access token (long-lived)
- Channel ID（数値）

Secret Manager に投入:

```bash
echo -n "<CHANNEL_SECRET>"       | gcloud secrets versions add driving-license-bot-line-channel-secret --data-file=-
echo -n "<CHANNEL_ACCESS_TOKEN>" | gcloud secrets versions add driving-license-bot-line-channel-access-token --data-file=-
echo -n "Uxxxx,Uyyyy"            | gcloud secrets versions add driving-license-bot-operator-line-user-ids --data-file=-
```

> `LINE_CHANNEL_ID` は env で渡す形（後の Cloud Run env で）。Phase 2+ の LINE
> Login プロバイダ作成時に `driving-license-bot-line-login-channel-secret`
> にも値を投入する。

---

## 5. Image を build & push

リポジトリルートから Cloud Build を起動（path dep の analytics-platform を含むため）:

```bash
make image-build
```

完了後、以下の image が利用可能:
- `asia-northeast1-docker.pkg.dev/sakamoto-family-agent/driving-license-bot/line-bot:<SHORT_SHA>`
- `asia-northeast1-docker.pkg.dev/sakamoto-family-agent/driving-license-bot/line-bot:latest`

---

## 6. Terraform で Cloud Run service deploy

`terraform/terraform.tfvars` を編集:

```hcl
line_bot_image = "asia-northeast1-docker.pkg.dev/sakamoto-family-agent/driving-license-bot/line-bot:latest"
```

再 apply:

```bash
make tf-apply
```

これで Cloud Run service `driving-license-bot-line-bot` が作られ、Webhook URL が出力される:

```bash
cd terraform && terraform output line_bot_webhook_url
# → https://driving-license-bot-line-bot-XXXX.a.run.app/webhook
```

---

## 7. LINE Webhook 登録 + 動作確認

[LINE Developers Console](https://developers.line.biz/console/) で:

1. Messaging API → Webhook 設定
2. **Webhook URL** に `terraform output line_bot_webhook_url` の値を貼る
3. **Use webhook** を ON
4. **Verify** ボタンで疎通確認 → 200 OK が返れば OK
5. **自動応答メッセージ / あいさつメッセージ** を OFF（Bot 側で制御するため）

LINE で Bot を友だち追加し、`クイズ` と送信 → シードの 30 問のうち 1 問が出れば成功。

---

## 8. 動作確認チェックリスト

- [ ] `クイズ` → 問題が表示される
- [ ] 番号 (`1` / `2`) で回答 → 採点 + 解説 + 根拠 URL が表示される
- [ ] `モード切替` → 仮免/本免が切り替わる
- [ ] `ヘルプ` → 使い方が表示される
- [ ] `データを削除` → 削除確認メッセージが表示される

---

## Teardown（2 モード）

| モード | 残るもの | CI plan | 用途 |
|---|---|---|---|
| `make teardown-app` | WIF / tfstate / API / sa-terraform-plan | ✅ 動作継続 | **課金停止したいが CI は維持**（推奨） |
| `make teardown` | （ほぼ）何も残らない | ❌ 再 bootstrap 必要 | 完全初期化 |

### `make teardown-app`（推奨）

```bash
make teardown-app
```

確認プロンプトで `yes` → app リソース（Cloud Run / Firestore / Secret 枠 /
Artifact Registry / sa-line-bot）が削除される。WIF / tfstate / API は残るので
`Terraform plan / driving-license-bot` ジョブは継続して動作する。

再展開:
```bash
# tfvars に line_bot_image を埋め直して
make tf-apply
```

### `make teardown`（完全削除）

```bash
make teardown
```

確認プロンプトで `yes` を入力すると:
1. Artifact Registry の image を全削除
2. `terraform destroy`（**WIF 含む全リソース**）
3. Secret Manager secret の即時削除

完了後の手動対応:
- LINE Developers Console で Webhook URL を解除 / アカウントを削除
- Cloud Logging のログは保持期間で自動削除
- GitHub repo Variables（WIF_PROVIDER 等）の削除（CI plan を再有効化したい場合は再登録）

完全初期化したい場合:

```bash
PURGE_STATE=true make teardown
# tfstate バケットも削除

# あるいは project ごと削除
gcloud projects delete $(gcloud config get-value project)
```

---

## コスト目安（Phase 1）

| サービス | 月額目安 |
|---|---|
| Cloud Run min=1 (CPU 1 / Mem 512Mi) | $5〜10 |
| Firestore（DAU 10〜50 程度） | $0〜数 $ |
| Secret Manager | 無料枠内 |
| Artifact Registry（< 1 GB） | < $1 |
| Cloud Logging / Monitoring | 無料枠内 |
| **Phase 1 合計** | **$5〜15 / 月** |

Phase 2+ で Cloud SQL / Vertex AI を加えると合算 **$40〜70/月** になる
（[INFRASTRUCTURE.md §10](./INFRASTRUCTURE.md#10-月額コスト試算再掲) 参照）。

---

## トラブルシューティング

| 症状 | 原因 / 対処 |
|---|---|
| `terraform apply` で permission denied | gcloud アカウントが Project Owner かを確認。`gcloud projects add-iam-policy-binding` で付与 |
| Webhook Verify が 401 / 503 | secret の値が空 / 間違い。`gcloud secrets versions list` で確認 |
| Cloud Run が 503 (cold start) | min_instance=1 が効いているか確認。tfvars の `line_bot_min_instances` |
| LINE 友だち追加で何も返らない | Cloud Logging で `resource.type=cloud_run_revision` をフィルタしてエラー確認 |
| `terraform destroy` で Firestore が消えない | `deletion_protection=false` で再 apply してから destroy |
