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

### 6.0 Cloud SQL pgvector（重複検査用、Phase 2-D 以降）

```bash
# インスタンス作成（db-f1-micro、最小構成）
gcloud sql instances create driving-license-bot-question-bank \
  --project=$GOOGLE_CLOUD_PROJECT \
  --tier=db-f1-micro \
  --database-version=POSTGRES_16 \
  --region=asia-northeast1 \
  --root-password="$(openssl rand -base64 24)"

# データベース + ユーザー作成
gcloud sql databases create question_bank \
  --instance=driving-license-bot-question-bank
gcloud sql users create app \
  --instance=driving-license-bot-question-bank \
  --password="$CLOUDSQL_PASSWORD"

# pgvector 拡張 + スキーマ作成
# Cloud SQL Auth Proxy をローカルで起動した上で:
psql -h 127.0.0.1 -U app -d question_bank <<'EOF'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS questions (
    question_id      TEXT PRIMARY KEY,
    version          INTEGER NOT NULL,
    body_hash        TEXT NOT NULL,
    embedding        vector(768) NOT NULL,
    applicable_goals TEXT[] NOT NULL,
    category         TEXT NOT NULL,
    difficulty       TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'needs_review',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS questions_embedding_ivfflat
    ON questions USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS questions_body_hash_idx ON questions (body_hash);
CREATE INDEX IF NOT EXISTS questions_status_idx ON questions (status);
EOF
```

`.env` に以下を追加:

```bash
QUESTION_BANK_BACKEND=pgvector
CLOUDSQL_INSTANCE_CONNECTION_NAME=$GOOGLE_CLOUD_PROJECT:asia-northeast1:driving-license-bot-question-bank
CLOUDSQL_DB=question_bank
CLOUDSQL_USER=app
CLOUDSQL_HOST=127.0.0.1   # Cloud SQL Auth Proxy 経由
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

---

## 7. オープン項目（運用開始前）

- [ ] 利用規約・プライバシーポリシーの公開（運営者名・連絡先・適用日を確定）
- [ ] LINE 公式アカウント設定で「自動応答メッセージ / あいさつメッセージ」を OFF
- [ ] Webhook URL を本番 URL に切替
- [ ] Rich Menu 画像のデザイン
- [ ] analytics-platform の `OTEL_EXPORTER_OTLP_ENDPOINT`（Langfuse 立て後）
