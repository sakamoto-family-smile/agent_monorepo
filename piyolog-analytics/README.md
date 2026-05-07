# piyolog-analytics

ぴよログ (育児記録アプリ) の .txt エクスポートを LINE Bot 経由で取り込み、
家族 (夫婦) で横断的に授乳・睡眠・排泄・体重等のサマリ / グラフを共有する個人用分析基盤。
LINE 上で Vertex Gemini を使った育児相談 + データ照会も可能。

> **Status**: Phase 4-B 完了、Phase 5+ (リマインド通知 / 多子対応) 計画中
>
> 設計書 / 機能要件 / 非機能要件 / アーキテクチャは [`docs/DESIGN.md`](docs/DESIGN.md) を参照。

**現在提供している機能**:
- `.txt` 添付 → パース → SQLite/Postgres に冪等保存
- LINE テキストコマンド: 期間サマリ / グラフ画像 / 取り消し / 相談モード
- リッチメニュー (8 ボタン) + Postback
- Vertex AI Gemini を使った相談 + 自然言語データ照会 (capability_gap タグで改善ループ)
- GCS バックアップ / リストア (`make backup` / `make restore`)
- 子情報設定 UI (Quick Reply で生年月日 / 名前)

---

## 0. Quickstart

### 0.1 前提

| ツール | バージョン |
|---|---|
| Python | 3.12+ |
| uv | 最新 |
| Docker / Docker Compose | 任意 (Cloud Build / 本番デプロイ時) |
| gcloud CLI | 任意 (本番デプロイ時) |

### 0.2 セットアップ

```bash
cd agent_monorepo/piyolog-analytics
cp .env.example .env
# .env を編集: LINE チャンネルの secret / access_token、家族の LINE userId (CSV) を埋める

uv sync
```

### 0.3 テスト / lint

```bash
make test         # pytest (250+ tests)
make lint         # ruff check
make check        # lint + test
```

### 0.4 ローカル起動

```bash
make run
# → http://localhost:8200/healthz で liveness 確認
# → ngrok 等で外部公開して LINE Messaging API webhook URL に
#   https://xxx.ngrok.app/api/line/webhook を登録
```

---

### 0.5.1 Cloud Run デプロイ (Cloud SQL + Secret Manager)

> **ステータス**: B2 (Docker 化 + Cloud Build + デプロイ scripts) ✅、B3 (Terraform で Cloud SQL / Secret Manager / sa-piyolog) ✅。

#### Step B3: Terraform で前提インフラを建てる

```bash
# 1. state バケット (一度だけ) と必要 API
gsutil mb -p $PROJECT -l US gs://${PROJECT}-tfstate || true
gsutil versioning set on gs://${PROJECT}-tfstate
gcloud services enable sqladmin.googleapis.com secretmanager.googleapis.com \
  artifactregistry.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
  iam.googleapis.com iamcredentials.googleapis.com --project=$PROJECT

# 2. tfvars + backend.tf 準備
cd terraform
cp terraform.tfvars.example terraform.tfvars        # project_id 等を埋める
cat >backend.tf <<EOF
terraform { backend "gcs" { bucket = "${PROJECT}-tfstate" prefix = "piyolog-analytics" } }
EOF

# 3. apply (Cloud SQL + Secret Manager 3 個 + sa-piyolog + Artifact Registry が立ち上がる)
cd ..
make tf-init
make tf-plan
make tf-apply

# 4. LINE secrets を投入 (LINE Developers Console から取得した値)
echo -n "$LINE_CHANNEL_SECRET" | \
  gcloud secrets versions add piyolog-line-channel-secret --data-file=- --project=$PROJECT
echo -n "$LINE_CHANNEL_ACCESS_TOKEN" | \
  gcloud secrets versions add piyolog-line-channel-access-token --data-file=- --project=$PROJECT

# 5. deploy_cloud_run.sh 用の env を一括出力
make tf-output-env                                   # → ../.env.deploy
```

詳細は [`terraform/README.md`](./terraform/README.md) 参照。

#### Image build (ローカル)

`pyproject.toml` に path dep (`../analytics-platform`) があるため、build context は **リポジトリルート** で固定:

```bash
make docker-build               # = piyolog-analytics:local

# ローカル起動 (SQLite + 自分の LINE channel secret)
LINE_CHANNEL_SECRET=... \
LINE_CHANNEL_ACCESS_TOKEN=... \
FAMILY_USER_IDS=Uxxx,Uyyy \
make docker-run
```

#### Cloud Build → Artifact Registry

```bash
# 事前: Artifact Registry repo を作成
gcloud artifacts repositories create piyolog-analytics \
  --repository-format=docker --location=us-central1 \
  --project=$PROJECT

# Cloud Build 経由で push (リポジトリルートを context に submit する)
PIYOLOG_GCP_PROJECT=$PROJECT \
PIYOLOG_AR_LOCATION=us-central1 \
PIYOLOG_AR_REPO=piyolog-analytics \
make cloudbuild-submit
# → ${LOCATION}-docker.pkg.dev/${PROJECT}/piyolog-analytics/piyolog-analytics:{SHORT_SHA, latest}
```

#### Cloud Run service デプロイ

前提 (B3 Terraform で作成想定):
- Cloud SQL (Postgres) instance
- Service Account `sa-piyolog@${PROJECT}.iam.gserviceaccount.com`
  - `roles/cloudsql.client`
  - `roles/secretmanager.secretAccessor`
- Secret Manager に 3 つのシークレット:
  - `piyolog-line-channel-secret` (LINE Messaging API channel secret)
  - `piyolog-line-channel-access-token` (LINE Messaging API access token)
  - `piyolog-database-url` (`postgresql+asyncpg://user:pass@/dbname?host=/cloudsql/<conn>`)

```bash
# B3 で出した env を読み込み (project / region / sa / cloud_sql_instance を自動セット)
set -a; source .env.deploy; set +a

# image を Cloud Build で push
PIYOLOG_GCP_PROJECT=$PROJECT make cloudbuild-submit

# 残りの env (LINE 関連 + 家族 userId) を渡してデプロイ
PIYOLOG_IMAGE_TAG=latest \
PIYOLOG_FAMILY_USER_IDS="Uxxx,Uyyy" \
PIYOLOG_FAMILY_ID=default \
make deploy-cloud-run
```

`deploy_cloud_run.sh` は:
- Cloud SQL connector を `--add-cloudsql-instances` で attach
- Secret Manager の 3 つを env としてマウント
- 残りの平文 env (`APP_ENV`, `FAMILY_ID`, `FAMILY_USER_IDS`, `ANALYTICS_*`) は `--update-env-vars` で渡す
- `--allow-unauthenticated` (LINE webhook はアプリ側で HMAC 検証するため、GCP 認証は不要)

デプロイ完了時に Cloud Run service URL と LINE webhook URL (`${URL}/api/line/webhook`) が出力される。LINE Developers Console の Webhook URL に登録すれば開通。

---

### 0.5 DB 切替 (SQLite ↔ Postgres)

`DATABASE_URL` で SQLAlchemy URL を指定する。同一コードが両 backend で動く。

| 用途 | URL |
|---|---|
| dev / test (既定) | `sqlite+aiosqlite:///./data/piyolog.db` |
| 本番 (Cloud SQL) | `postgresql+asyncpg://user:pass@host:5432/piyolog` |

```bash
# dev: 起動時 create_all で自動初期化 (DB_AUTO_CREATE=true、既定)
make run

# Postgres 接続例 (Cloud SQL Proxy + Alembic で migration)
DATABASE_URL=postgresql+asyncpg://piyolog:secret@127.0.0.1:5432/piyolog \
DB_AUTO_CREATE=false \
make migrate
DATABASE_URL=postgresql+asyncpg://piyolog:secret@127.0.0.1:5432/piyolog \
DB_AUTO_CREATE=false \
make run
```

`PIYOLOG_DB_PATH` (旧) 単独設定でも `DATABASE_URL` が空なら自動的に SQLite として解決する (後方互換)。Alembic migration は [`alembic/`](./alembic/) 参照。

---

### 0.5.2 開通手順 (実機 dogfood)

家族の LINE bot として常時稼働させるための **9 ステップ walkthrough**。各ステップは idempotent なので途中で詰まったら同じコマンドを再実行できる。

#### Step 1. GCP project の準備

```bash
export PROJECT="your-gcp-project-id"
gcloud config set project "$PROJECT"
gcloud auth login
gcloud auth application-default login

# state bucket + 必要 API をまとめて有効化
PIYOLOG_GCP_PROJECT="$PROJECT" make bootstrap-gcp
```

#### Step 2. Terraform でインフラ作成 (Cloud SQL + Secret Manager + SA + Artifact Registry)

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars      # region / name_prefix を必要なら編集
cat >backend.tf <<EOF
terraform {
  backend "gcs" {
    bucket = "${PROJECT}-tfstate"
    prefix = "piyolog-analytics"
  }
}
EOF
cd ..

export TF_VAR_project_id="$PROJECT"
make tf-init
make tf-plan       # 内容確認 (Cloud SQL instance / 3 secrets / SA / AR repo が plan に出る)
make tf-apply      # 5〜8 分かかる (Cloud SQL の起動が遅い)
```

#### Step 3. LINE Messaging API channel の作成

[LINE Developers Console](https://developers.line.biz/console/) で:
1. プロバイダー作成 (家族用)
2. **Messaging API** チャンネル作成
3. 「Messaging API設定」タブで:
   - `Channel access token (long-lived)` を発行
   - `Channel secret` を「チャンネル基本設定」からメモ

#### Step 4. LINE secret を Secret Manager に投入

```bash
echo -n "$LINE_CHANNEL_SECRET" | \
  gcloud secrets versions add piyolog-line-channel-secret --data-file=- --project=$PROJECT

echo -n "$LINE_CHANNEL_ACCESS_TOKEN" | \
  gcloud secrets versions add piyolog-line-channel-access-token --data-file=- --project=$PROJECT

# DATABASE_URL は TF が既に投入済 (確認だけ)
gcloud secrets versions list piyolog-database-url --project=$PROJECT
```

#### Step 5. image を Cloud Build → Artifact Registry に push

```bash
PIYOLOG_GCP_PROJECT="$PROJECT" \
PIYOLOG_AR_LOCATION="us-central1" \
PIYOLOG_AR_REPO="piyolog-analytics" \
make cloudbuild-submit
# → ${LOCATION}-docker.pkg.dev/${PROJECT}/piyolog-analytics/piyolog-analytics:{SHORT_SHA, latest}
```

#### Step 6. **bootstrap mode** で Cloud Run deploy (許可リスト空)

家族の LINE userId を取得するため、最初は `FAMILY_USER_IDS` を空のまま deploy する。bootstrap mode では受信した userId を Cloud Logging に WARN レベルで出すだけで、メッセージへの応答はしない。

```bash
# TF output から env を流し込む
make tf-output-env                                # → ../.env.deploy
set -a; source .env.deploy; set +a

# 残り env (空の userId 許可リスト)
PIYOLOG_IMAGE_TAG="latest" \
PIYOLOG_FAMILY_USER_IDS="" \
PIYOLOG_FAMILY_ID="default" \
make deploy-cloud-run
# → 出力された Cloud Run service URL を控える
#    例: https://piyolog-analytics-xxxxxxx.a.run.app
```

#### Step 7. LINE Webhook URL を Console に登録

LINE Developers Console > Messaging API > 「Webhook URL」に:
```
https://piyolog-analytics-xxxxxxx.a.run.app/api/line/webhook
```

「Webhookの利用」を **ON**、「応答メッセージ」を **OFF** に切替。「検証」ボタンで疎通確認 (200 が返れば OK)。

#### Step 8. 自分の LINE userId を取得して `FAMILY_USER_IDS` 更新

家族メンバー全員に bot を **友だち追加** してもらい、各自から bot に何かテキスト (例: `hi`) を送ってもらう。Cloud Logging で:

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND
   resource.labels.service_name="piyolog-analytics" AND
   textPayload=~"\\[bootstrap\\] FAMILY_USER_IDS unset"' \
  --project=$PROJECT --limit=20 --format='value(textPayload)'
```

`line_user_id=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxx` の userId を全員分集めて CSV で繋ぎ、`FAMILY_USER_IDS` を埋めて再 deploy:

```bash
PIYOLOG_IMAGE_TAG="latest" \
PIYOLOG_FAMILY_USER_IDS="Uaaaaaaa...,Ubbbbbbb..." \
make deploy-cloud-run
```

#### Step 9. 実機テスト

家族メンバーが順番に LINE で bot に:
- ぴよログから export した `.txt` を添付 → 取り込み完了の push が返る
- `今日` / `週間` / `月間` でサマリ確認
- リッチメニューから各機能をテスト

Cloud Logging で `[upload] cycle: uploaded=N` のログ (= analytics-platform に JSONL を流せている) も確認。

#### よくある詰まりどころ

| 症状 | 原因 / 対処 |
|---|---|
| Webhook 検証で 401 | LINE channel secret が Secret Manager と Console で食い違っている |
| Webhook 検証で 503 | `LINE_CHANNEL_SECRET` か `LINE_CHANNEL_ACCESS_TOKEN` が secret に投入されていない |
| 自分の userId が log に出ない | bootstrap mode で deploy できていない (`FAMILY_USER_IDS` を空にして再 deploy) |
| `.txt` 添付しても応答ゼロ | `FAMILY_USER_IDS` に自分の userId が入っていない (Step 8 をやり直す) |
| Cloud SQL に接続できない | `sa-piyolog` の SA が deploy 時に紐付いているか (`gcloud run services describe ...` で確認) |

---

### 0.6 LINE userId 取得手順 (補足)

`FAMILY_USER_IDS` には 33 文字の LINE User ID (`U` + 32 hex) を入れる必要がある。
取得の **3 通り** を、簡単な順に記載:

#### A. 自分の Channel に紐付いた User ID を表示する (最速)

LINE Developers Console > 対象 Provider > 対象 Channel > Basic settings タブで:
- "Your user ID" 欄に自分の User ID が直接表示される
- ただし「Bot 開発者本人」の User ID であり、家族メンバの ID は別途必要

#### B. webhook ログから拾う (推奨、家族の ID も取れる)

bootstrap mode (`FAMILY_USER_IDS` 未設定 / 空) で deploy しておけば、line_handler が
完全な userId を WARN ログに出す。詳細は `0.5.2 Step 8` 参照。

#### C. SQLite / Postgres から拾う (取り込み実績がある場合)

```bash
# SQLite
sqlite3 data/piyolog.db "SELECT DISTINCT source_user_id FROM piyolog_events;"
# Postgres
psql ... -c "SELECT DISTINCT source_user_id FROM piyolog_events"
```

---

## 1. 監視・運用

| 症状 | 確認ポイント |
|---|---|
| 署名検証 401 | `LINE_CHANNEL_SECRET` と LINE Developers Console の Channel secret 一致確認 |
| 503 応答 | `.env` に LINE 認証情報が設定されているか、プロセス再起動後に反映されたか |
| 応答が返らない | `FAMILY_USER_IDS` に自分の LINE userId が入っているか (LINE Developers の userId は webhook ログから確認) |
| 取り込み時 `InvalidPiyologFileError` | ぴよログアプリから export した .txt をそのまま送信しているか (UTF-8 / cp932 自動判定) |
| サマリが空 | `event_date` (JST) と指定期間が一致しているか、`import_batches.rolled_back_at IS NULL` か |
| LLM 相談で `capability_gap=tool_error` 多発 | tool_executor の DB 接続 / family_id 一致を確認 |

データ確認クエリ:
```bash
sqlite3 data/piyolog.db "SELECT event_date, event_type, COUNT(*) FROM piyolog_events GROUP BY 1, 2 ORDER BY 1 DESC LIMIT 20;"
```

---

## 2. 関連ドキュメント

このエージェントの設計や運用詳細は別ファイルに分離している:

- [`docs/DESIGN.md`](docs/DESIGN.md) — システム全体設計書 (機能要件 F1〜F14 / 非機能要件 / アーキテクチャ / Roadmap / 設計判断ログ / セキュリティ / テスト戦略)
- [`docs/BACKUP_RESTORE.md`](docs/BACKUP_RESTORE.md) — Phase 4-A バックアップ / リストア手順
- [`docs/SETTINGS.md`](docs/SETTINGS.md) — Phase 4-B 子情報 設定 UI 仕様
- [`alembic/`](alembic/) — DB マイグレーション (0001 → 0002 session/conversation → 0003 children)
- [`terraform/README.md`](terraform/README.md) — Terraform IaC 詳細
- [`../docs/PROPOSALS/`](../docs/PROPOSALS/) — モノレポ共通の機能個別 ADR
- [モノレポ全体の設計テンプレート](../docs/) — `SYSTEM_DESIGN_TEMPLATE.md` / `README_TEMPLATE.md` / `PROPOSALS/TEMPLATE.md`
