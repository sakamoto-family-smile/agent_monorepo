# セットアップ手順

driving-license-bot をローカル / 本番環境で起動するための準備ガイド。
設計の全体像は [DESIGN.md](./DESIGN.md) / [INFRASTRUCTURE.md](./INFRASTRUCTURE.md) を参照。

---

## 1. 前提

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- gcloud CLI（GCP 連携時）
- LINE Developers Console アカウント

---

## 2. LINE Messaging API（Bot）チャネル作成

1. [LINE Developers Console](https://developers.line.biz/console/) にログイン
2. **Provider** を作成（既存があれば選択）
   - 例: `driving-license-bot-provider`
3. **Messaging API channel** を作成
   - チャネル名: 例「学科試験対策 Bot」
   - チャネル説明、業種等を入力
4. 作成後、以下の値を控える:
   - **Channel ID**（数値）
   - **Channel secret**（"Basic settings" タブ）
   - **Channel access token (long-lived)**（"Messaging API" タブ → Issue で発行）
5. **Webhook 設定**:
   - Webhook URL: `https://<your-cloud-run-host>/webhook`
   - Use webhook: ON
   - Auto-reply messages / Greeting messages: OFF（Bot 側で制御するため）

---

## 3. LINE Login プロバイダ準備（Phase 2+ の複数 Bot 名寄せ用、Phase 1.5 で先行作成）

複数 Bot 展開時の名寄せ（DESIGN.md §8.5）に備えて、LINE Login プロバイダを
**今のうちに作成しておく**。Phase 1.5 では未使用だが、後から Bot を別 provider
に作ってしまうと統合不可能になる。

1. LINE Developers Console で **同じ Provider 配下に LINE Login channel を追加**
   - チャネル名: 例「学科試験対策 Login」
   - アプリタイプ: Web app
2. 以下を控える:
   - **LINE Login Channel ID**
   - **LINE Login Channel secret**
3. 環境変数として保管（`.env` に `LINE_LOGIN_CHANNEL_ID` / `LINE_LOGIN_CHANNEL_SECRET`）

> Phase 2+ で LIFF / OpenID Connect を導入する際、ここで作った Channel の `sub` を
> `internal_uid` に紐付けることで複数 Bot を横断識別できるようになる。

---

## 4. ローカル開発

```bash
cd driving-license-bot
cp .env.example .env

# .env を編集（最低限）
# REPOSITORY_BACKEND=memory   ← ローカルは in-memory で OK
# LINE_CHANNEL_SECRET=...
# LINE_CHANNEL_ACCESS_TOKEN=...
# LINE_CHANNEL_ID=...

make install
make test                                 # pytest（41 件）
make run                                  # uvicorn http://localhost:8080
```

LINE Webhook をローカルから叩けるよう、別ターミナルで [ngrok](https://ngrok.com/)
等を立てて Webhook URL を LINE Developers Console に設定:

```bash
ngrok http 8080
# → https://<random>.ngrok.io/webhook を Webhook URL に設定
```

---

## 5. Rich Menu の作成

Rich Menu の画像（2500x843 PNG）を用意して以下を実行:

```bash
LINE_CHANNEL_ACCESS_TOKEN=... uv run python scripts/provision_rich_menu.py \
    --image path/to/menu.png \
    --delete-existing
```

レイアウトは [scripts/provision_rich_menu.py](../scripts/provision_rich_menu.py)
の `build_rich_menu_request` 参照（5 ボタン: クイズ / モード切替 / ヘルプ /
現在のモード / データを削除）。

---

## 6. GCP（本番）への切替

### 6.A 問題生成バッチ（Phase 2-E 以降）

Cloud Run Job + Cloud Workflows + Cloud Scheduler で問題プールを夜間補充する。

#### 6.A.1 Service Account の前提

事前に以下の SA を作成し、必要権限を付与しておく:

| SA | 権限 |
|---|---|
| `sa-batch` | `roles/aiplatform.user`、Cloud SQL client、Secret Manager accessor |
| `sa-workflow` | `roles/run.invoker`、Cloud Logging |
| `sa-scheduler` | `roles/workflows.invoker` |

#### 6.A.2 Image build & push

\`\`\`bash
gcloud builds submit \\
  --config=driving-license-bot/cloudbuild.yaml \\
  --substitutions=_LOCATION=asia-northeast1,_REPO=driving-license-bot \\
  driving-license-bot/
\`\`\`

#### 6.A.3 デプロイ（Job + Workflow + Scheduler を一括）

\`\`\`bash
cd driving-license-bot
GOOGLE_CLOUD_PROJECT=$PROJECT \\
ANTHROPIC_VERTEX_PROJECT_ID=$PROJECT \\
CLOUDSQL_INSTANCE_CONNECTION_NAME=$PROJECT:asia-northeast1:driving-license-bot-question-bank \\
CLOUDSQL_DB=question_bank \\
CLOUDSQL_USER=app \\
CLOUDSQL_PASSWORD_SECRET=driving-license-bot-cloudsql-password \\
LINE_CHANNEL_SECRET_NAME=driving-license-bot-line-channel-secret \\
LINE_CHANNEL_ACCESS_TOKEN_NAME=driving-license-bot-line-channel-access-token \\
GENERATION_BATCH_SIZE=20 \\
BATCH_SCHEDULE_CRON="0 17 * * *" \\
./scripts/deploy_batch.sh
\`\`\`

`BATCH_SCHEDULE_CRON` は UTC で指定（例: `0 17 * * *` = 毎日 02:00 JST）。
`SCHEDULER_TIMEZONE` を `Asia/Tokyo` にすれば JST 直接指定も可。

#### 6.A.4 手動トリガ

\`\`\`bash
gcloud workflows execute driving-license-bot-generation-pipeline \\
  --project=$PROJECT --location=asia-northeast1 \\
  --data='{"project":"'"$PROJECT"'","total":5,"difficulty":"standard"}'
\`\`\`

#### 6.A.5 監視

- Cloud Logging で `resource.type=workflows.googleapis.com/Workflow` をフィルタ
- analytics-platform の `mart_generation_health`（PR E 以降に追加）で
  生成成功率・カテゴリ別品質・cross-check 不一致頻度を集計
- `pool_low_alert` business_event が emit されたら運営者の LINE に通知（Phase 5）

### 6.0 Cloud SQL pgvector（重複検査用、Phase 2-A）

#### 6.0.1 インスタンス作成

Phase 2-A1 で **Terraform 化済**。`make tf-apply` で以下が自動作成される:

- Cloud SQL Postgres 15 instance: `driving-license-bot-pg` (db-f1-micro, asia-northeast1)
- Database: `question_bank`
- User: `app` (password は `random_password` で生成され `driving-license-bot-cloudsql-password`
  Secret Manager に格納)

詳細は [terraform/README.md](../terraform/README.md) と [terraform/cloudsql.tf](../terraform/cloudsql.tf)。

#### 6.0.2 Cloud SQL Auth Proxy のインストール

Cloud Run / ローカル両方から Cloud SQL に接続するため Auth Proxy を使う（VPC Connector
は Phase 3+ 先送り）。

```bash
gcloud components install cloud-sql-proxy
# または: https://cloud.google.com/sql/docs/postgres/sql-proxy#install
```

#### 6.0.3 スキーマ投入（PR A2 で追加）

```bash
# ターミナル A: Auth Proxy を起動（127.0.0.1:5432 で listen）
cd driving-license-bot
make cloudsql-proxy

# ターミナル B: スキーマ投入 + 動作確認
make cloudsql-init       # CREATE EXTENSION vector + questions + index
make cloudsql-verify     # add → find_similar → count → cleanup の smoke
```

`make cloudsql-init` の出力例:

```
[init_schema] connecting host=127.0.0.1 port=5432 db=question_bank user=app
[init_schema] applying DDL ...
[init_schema] verifying ...
[init_schema] vector extension: v0.7.0
[init_schema] questions columns (9): question_id, version, body_hash, embedding, ...
[init_schema] indexes (4): questions_body_hash_idx, questions_embedding_ivfflat, ...
[init_schema] questions row count: 0
[init_schema] OK.
```

`make cloudsql-verify` の出力例:

```
[verify_qb] ✓ add (12.3 ms)
[verify_qb] ✓ find_similar top score=1.000000 (1 hits, 8.9 ms)
[verify_qb] ✓ find_by_body_hash
[verify_qb] ✓ count = 1
[verify_qb] ALL OK.
```

> teardown-app 後の再投入も同コマンドで可能（DDL は `IF NOT EXISTS`）。

#### 6.0.4 アプリ側 `.env` 設定

```bash
QUESTION_BANK_BACKEND=pgvector
CLOUDSQL_INSTANCE_CONNECTION_NAME=$GOOGLE_CLOUD_PROJECT:asia-northeast1:driving-license-bot-pg
CLOUDSQL_DB=question_bank
CLOUDSQL_USER=app
CLOUDSQL_HOST=127.0.0.1   # Cloud SQL Auth Proxy 経由（Cloud Run では unix socket 使用）
CLOUDSQL_PORT=5432
```

依存をインストール: `uv sync --extra pgvector`

### 6.1 Firestore

```bash
gcloud firestore databases create \
  --project=$GOOGLE_CLOUD_PROJECT \
  --location=asia-northeast1 \
  --type=firestore-native
```

`.env` に以下を設定:

```bash
REPOSITORY_BACKEND=firestore
GOOGLE_CLOUD_PROJECT=your-gcp-project
FIRESTORE_DATABASE=(default)
```

### 6.2 Secret Manager

```bash
echo -n "$LINE_CHANNEL_SECRET" | gcloud secrets create \
  driving-license-bot-line-channel-secret --data-file=-

echo -n "$LINE_CHANNEL_ACCESS_TOKEN" | gcloud secrets create \
  driving-license-bot-line-channel-access-token --data-file=-
```

Cloud Run の Service Account に accessor 権限を付与（INFRASTRUCTURE.md §4 参照）。

### 6.3 Cloud Run へのデプロイ

```bash
make docker-build       # リポジトリルートから build
gcloud run deploy line-bot-service \
  --image=asia-northeast1-docker.pkg.dev/$GOOGLE_CLOUD_PROJECT/driving-license-bot/line-bot:latest \
  --region=asia-northeast1 \
  --service-account=sa-line-bot@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com \
  --min-instances=1 \
  --set-env-vars=REPOSITORY_BACKEND=firestore,GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT,LINE_CHANNEL_ID=$LINE_CHANNEL_ID \
  --set-secrets=LINE_CHANNEL_SECRET=driving-license-bot-line-channel-secret:latest,LINE_CHANNEL_ACCESS_TOKEN=driving-license-bot-line-channel-access-token:latest
```

### 6.4 Webhook URL を LINE Console に登録

デプロイ完了後の URL を `https://<cloud-run-url>/webhook` として LINE Developers
Console の Webhook URL に設定。

### 6.5 review-admin-ui (App-level Google OAuth, Phase 2-C3)

運営者向けレビュー Web UI を、アプリ内蔵の Google OAuth + signed session cookie
で認証する。Cloud Run service 自体は `allUsers` invoker（パブリック）として公開し、
未ログイン request は `/login` にリダイレクト → Google → `/auth/callback` で認証情報を
session cookie に保存 → email allowlist で認可、という流れ。

> **なぜ IAP ではないか:** Cloud Run direct IAP は個人 GCP project（組織所属なし）で
> OAuth client の自動 provisioning が動かず "Empty Google Account OAuth client ID(s)/secret(s)"
> エラーで利用不可。同じ理由で legacy IAP の `gcloud iap oauth-brands` も `Project must
> belong to an organization` で蹴られる。App-level OAuth は組織不要で、PC・スマホどちらでも
> 通常のブラウザログインで動く。

#### 6.5.1 OAuth consent screen を configure（1 度だけ）

GCP Console で:

1. **APIs & Services > OAuth consent screen**: https://console.cloud.google.com/apis/credentials/consent
2. **External**（個人 Google アカウント）を選択して "Create"
3. App name: `driving-license-bot-admin`、User support email + Developer contact email を入力
4. **Test users** に運営者の Google アカウント email を追加（External + Testing の場合は test user 必須）
5. **Save and continue**（Scopes は default で OK）

> "Internal" は Google Workspace 限定。個人 GCP project では External を選ぶ。
> Publishing status は "Testing" のままで OK（test users に登録した email でログイン可能）。

#### 6.5.2 OAuth 2.0 Client ID を作成

1. **APIs & Services > Credentials**: https://console.cloud.google.com/apis/credentials
2. **+ CREATE CREDENTIALS > OAuth client ID**
3. Application type: **Web application**
4. Name: `driving-license-bot-admin-oauth`
5. Authorized redirect URIs: 一旦空のまま **CREATE**（Cloud Run URL がまだ確定していないため）
6. ダイアログで表示される **Client ID** と **Client Secret** をコピー保存

#### 6.5.3 Secret Manager に値を投入

```bash
# OAuth Client ID
echo -n "123456789012-xxx.apps.googleusercontent.com" | \
  gcloud secrets versions add driving-license-bot-admin-oauth-client-id --data-file=-

# OAuth Client Secret
echo -n "GOCSPX-xxxxxxxxxxxx" | \
  gcloud secrets versions add driving-license-bot-admin-oauth-client-secret --data-file=-

# Session secret (32 bytes ランダム)
openssl rand -hex 32 | \
  gcloud secrets versions add driving-license-bot-admin-session-secret --data-file=-
```

> Secret 枠自体は terraform で作成済 (`make tf-apply` 後に `gcloud secrets list` で確認可能)。
> 初回 apply はこの 3 つの secret に value version が無い状態でも進む（Cloud Run service
> 起動時に Secret Manager 参照で 500 になるので、必ず value 投入後に再 apply or revision 再生成）。

#### 6.5.4 tfvars に値を設定

```hcl
# image は line-bot と共有（CMD で uvicorn review_admin_ui.main:app に切替）
review_admin_image = "asia-northeast1-docker.pkg.dev/<PROJECT>/driving-license-bot/line-bot:latest"

# App-level OAuth でログイン許可する email リスト (空なら fail-closed)
review_admin_allowed_emails = ["operator@example.com"]
```

#### 6.5.5 Apply + URL 確認

```bash
make tf-apply
cd terraform && terraform output review_admin_url review_admin_oauth_redirect_url
# review_admin_url               = "https://driving-license-bot-admin-ui-XXXX.a.run.app"
# review_admin_oauth_redirect_url = "https://driving-license-bot-admin-ui-XXXX.a.run.app/auth/callback"
```

#### 6.5.6 OAuth client に redirect URI を登録

6.5.5 で取得した `review_admin_oauth_redirect_url` を Console で登録:

1. **APIs & Services > Credentials > OAuth 2.0 Client IDs > driving-license-bot-admin-oauth**
2. **Authorized redirect URIs > + ADD URI**: `https://driving-license-bot-admin-ui-XXXX.a.run.app/auth/callback`
3. **Save**

これで OAuth client が Cloud Run service の callback URL を受け入れるようになる。

#### 6.5.7 ブラウザでログイン確認

PC でも iPad でも `review_admin_url` を開くと:

1. 未ログインなら自動で `/login` → Google アカウント選択
2. 初回は consent screen (Test users 登録済みなら警告は出るが進める)
3. `/auth/callback` 経由で session cookie が降って `/` (review queue) が表示
4. allowlist 外の email でログインすると 403
5. session 寿命は 7 日（`ADMIN_SESSION_MAX_AGE_SECONDS` で変更可能）

---

## 7. オープン項目（運用開始前）

- [ ] 利用規約・プライバシーポリシーの公開（運営者名・連絡先・適用日を確定）
- [ ] LINE 公式アカウント設定で「自動応答メッセージ / あいさつメッセージ」を OFF
- [ ] Webhook URL を本番 URL に切替
- [ ] Rich Menu 画像のデザイン
- [ ] analytics-platform の `OTEL_EXPORTER_OTLP_ENDPOINT`（Langfuse 立て後）
