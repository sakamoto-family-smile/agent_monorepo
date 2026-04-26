# piyolog-analytics

ぴよログ (育児記録アプリ) の .txt エクスポートを LINE Bot 経由で取り込み、
家族 (夫婦) で横断的に授乳・睡眠・排泄・体重等のサマリを共有する個人用分析基盤。

**Phase 1 (本 PR) の提供機能**:

- `.txt` 添付 → パース → SQLite に冪等保存
- LINE テキストコマンドで期間サマリ返信 (`今日` / `昨日` / `週間` / `月間` / `期間 YYYY-MM-DD YYYY-MM-DD`)
- 家族 (夫婦) の複数 LINE userId を同じ family として集計
- 許可リスト外の userId は無応答 (silent drop)
- `analytics-platform` (モノレポ共通) に webhook 受信・取り込み成否を emit

**後続フェーズ**:

- Phase 1.5: グラフ可視化 (matplotlib) + ロールバックコマンド
- Phase 2: リッチメニュー (Postback)
- Phase 3: Claude 相談機能 (prompt caching + 緊急キーワードゲート)

詳細: [`docs/design.md`](./docs/design.md)

---

## 0. Quickstart

### 0.1 前提

| ツール | バージョン |
|---|---|
| Python | 3.12+ |
| uv | 最新 |

### 0.2 セットアップ

```bash
cd agent_monorepo/piyolog-analytics
cp .env.example .env
# .env を編集: LINE チャンネルの secret / access_token、家族の LINE userId (CSV) を埋める
make install
```

### 0.3 テスト / lint

```bash
make test      # 全スイート実行
make lint      # ruff
make check     # lint + test
```

### 0.4 ローカル起動

```bash
make run
# → http://localhost:8200/healthz で liveness 確認
# → ngrok 等で外部公開して LINE Messaging API webhook URL に
#   https://xxx.ngrok.app/api/line/webhook を登録
```

---

### 0.5.1 Cloud Run デプロイ (B 案 Step 2-3: 本格 GCP 化)

> **ステータス**: B2 (Docker 化 + Cloud Build + デプロイ scripts) ✅、B3 (Terraform で Cloud SQL / Secret Manager / sa-piyolog) ✅。完全開通 (B4: LINE webhook URL 切替) は次 PR。

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

### 0.5 DB 切替 (B 案 Step 1: Postgres 化)

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

`PIYOLOG_DB_PATH` (旧) 単独設定でも `DATABASE_URL` が空なら自動的に SQLite として解決する (後方互換)。Alembic migration は `alembic/README.md` 参照。

---

### 0.5.2 開通手順 (B 案 Step 4: 実機 dogfood)

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

Cloud Logging で `[upload] cycle: uploaded=N` のログ (= analytics-platform に JSONL を流せている) も確認。1〜2 週間 dogfood して使い勝手を確認する。

#### よくある詰まりどころ

| 症状 | 原因 / 対処 |
|---|---|
| Webhook 検証で 401 | LINE channel secret が Secret Manager と Console で食い違っている |
| Webhook 検証で 503 | `LINE_CHANNEL_SECRET` か `LINE_CHANNEL_ACCESS_TOKEN` が secret に投入されていない |
| 自分の userId が log に出ない | bootstrap mode で deploy できていない (`FAMILY_USER_IDS` を空にして再 deploy) |
| `.txt` 添付しても応答ゼロ | `FAMILY_USER_IDS` に自分の userId が入っていない (Step 8 をやり直す) |
| Cloud SQL に接続できない | `sa-piyolog` の SA が deploy 時に紐付いているか (`gcloud run services describe ...` で確認) |

---

## 1. アーキテクチャ (Phase 1)

```
┌─────────────┐
│ LINE User   │ (家族 N 人、許可リスト制)
└──────┬──────┘
       │ .txt 添付 or テキストコマンド
       ▼
┌──────────────────────────────────────────┐
│ FastAPI piyolog-analytics (port 8200)    │
│                                          │
│  POST /api/line/webhook                  │
│   ├─ FileMessage → download → parse →    │
│   │    repo.import_events → push 完了    │
│   ├─ TextMessage → command_router →      │
│   │    summarize → reply_text            │
│   └─ 認証: X-Line-Signature              │
│                                          │
│  GET /healthz                            │
└──────────────────────────────────────────┘
       │                   │
       ▼                   ▼
 ┌──────────────────┐  ┌─────────────────┐
 │ SQLite (dev/test)│  │ analytics-      │
 │ Postgres (prod)  │  │ platform        │
 │   via SQLAlchemy │  │ JSONL → DuckDB  │
 └──────────────────┘  └─────────────────┘
```

主要コンポーネント:

| モジュール | 責務 |
|---|---|
| `app/parser/piyolog_parser.py` | ぴよログ .txt → `ParseResult` (pure Python) |
| `app/repositories/event_repo.py` | SQLite UPSERT + 冪等 event_id |
| `app/services/analytics.py` | 期間集計 + テキスト整形 |
| `app/services/command_router.py` | テキストコマンド解釈 |
| `app/services/line_client.py` | LINE SDK v3 ラッパ (text + file) |
| `app/services/line_handler.py` | Event 分岐 (ack reply → bg import → push) |
| `app/services/import_service.py` | bytes → decode → parse → repo |
| `app/routes/line.py` | FastAPI webhook + 署名検証 |
| `app/instrumentation/setup.py` | analytics-platform 初期化 |

---

## 2. コマンド仕様 (Phase 1)

| 入力 | 動作 |
|---|---|
| `ヘルプ` / `help` / `menu` | コマンド一覧 |
| `今日` / `today` | 今日 (JST) のサマリ |
| `昨日` / `yesterday` | 昨日サマリ |
| `週間` / `week` | 直近 7 日 (今日含む) |
| `月間` / `month` | 今月 (1日〜今日) |
| `期間 YYYY-MM-DD YYYY-MM-DD` / `period ...` | 指定期間 |
| `.txt` 添付 | ぴよログエクスポートを取り込み |

サマリ出力例 (1 日):

```
📅 2026/04/22 のサマリ

🍼 ミルク 2回 260ml / 搾母乳 1回 80ml
🤱 母乳 1回 / 左5分 右5分
💤 睡眠 10時間30分 (日中 2時間0分 / 夜間 8時間30分)
💧 おしっこ 1回 / うんち 1回
🍽️ 離乳食 1回 / お風呂 1回 / お薬 1回
🌡️ 体温 36.8°C (最終 04/22 20:10)
⚖️ 体重 8.50kg (最終 04/22 20:00)
📏 身長 72.0cm (最終 04/22 20:05)
```

---

## 3. データモデル (Phase 1)

### `piyolog_events` (SQLite)

| カラム | 説明 |
|---|---|
| event_id | `sha1(family_id + ISO8601 ts + event_type + raw)` |
| family_id | 集計単位キー |
| source_user_id | 取り込んだ LINE userId |
| child_id | `DEFAULT_CHILD_ID` (Phase 1 固定) |
| event_timestamp | ISO8601 (+09:00) |
| event_date | YYYY-MM-DD (JST、冗長集計キー) |
| event_type | `formula` / `breast_milk` / `expressed_milk` / `sleep` / `wake` / `pee` / `poo` / `temperature` / `weight` / `height` / `head_circumference` / `bath` / `medicine` / `baby_food` / `memo` / `other` |
| volume_ml / left_minutes / right_minutes / sleep_minutes / temperature_c / weight_kg / height_cm / head_circumference_cm | 型別フィールド |
| memo | コメント・パース不能行フォールバック |
| raw_text | 原文 1 行 |
| import_batch_id / imported_at | バッチ追跡 |

### `import_batches`

取り込み単位のメタ情報。同じ原本 (raw_text hash) を 2 回送ると
`DuplicateImportError` で弾き、ユーザに「すでに取り込み済み」を返す。

---

## 4. 観測性 (analytics-platform 連携)

| タイミング | 発行 event_type |
|---|---|
| webhook 受信開始 | `conversation_event` (started) |
| import 成否・webhook 処理 | `business_event` (domain=piyolog, action=line_webhook_processed) |
| 個別イベント処理失敗 | `error_event` |
| webhook 受信終了 | `conversation_event` (ended) |

`LINE userId` は raw では流さない (body を sha256 ハッシュ化した値のみ記録)。

---

## 5. セキュリティ

| 項目 | 対策 |
|---|---|
| LINE Webhook 偽装 | X-Line-Signature (HMAC-SHA256) 検証 |
| 不正ユーザー | `FAMILY_USER_IDS` 許可リスト、外は silent drop |
| ファイル検証 | サイズ上限 5MB (`UPLOAD_MAX_BYTES`) + `【ぴよログ】` ヘッダ必須 |
| シークレット | `.env` (gitignore)、本番は Secret Manager を想定 |
| 監視登録 | `security-platform/config/inventory.yaml` / `scan.yaml` に登録済 |

---

## 6. 残課題と次フェーズ

MVP (Phase 1) がマージ済。本節は **次回着手時に planning コストをかけず着手できるレベルの詳細タスク** を記載する。hotcook-agent のロードマップ流儀 (PR #32) に準拠。

### Phase 1 残 TODO (MVP 後のフォロー)

Phase 1 の Definition of Done に対して、実機運用で顕在化しうる項目:

- [ ] **実機 dogfooding**: LINE Developers Console で Channel 作成 → `.env` 設定 → 自分の LINE userId を `FAMILY_USER_IDS` に登録 → ngrok で webhook を立てる → 過去 1 週間分の .txt で取り込み確認
- [ ] **Noto Sans CJK フォント**: Phase 1.5 のグラフで必須。hotcook-agent / lifeplanner-agent が既に使っている置き場所 (`analytics-platform` 共通 or 各エージェント内) を確認し、fontconfig の探索パスを揃える
- [ ] **`setup_database.sh`**: SQLite の初期化を手動で打てる形に。Phase 1 は lifespan 経由で自動初期化しているが、ops 用途で欲しい
- [ ] **LINE userId 確認手順の README 明記**: 現状は「webhook ログから拾う」記載のみ。LINE Developers の User ID 取得方法をもう少し丁寧に書く
- [ ] **コマンド aliases 検証**: `today` / `week` が意図通り半角・全角空白両方でマッチするかを実機で
- [ ] **Phoenix トレース動作確認** (analytics-platform 起動時): `OTEL_EXPORTER_OTLP_ENDPOINT` を設定した場合に span が Phoenix UI で見えるか

---

### Phase 1.5 (次の PR): グラフ + ロールバック

**目標**: LINE でグラフ画像を返せる状態 + 誤って取り込んだ .txt をコマンドで無効化できる状態。

#### グラフ可視化 (matplotlib)

- [ ] `app/services/visualizer.py` を新設し、以下 5 種の純関数を実装:
  - [ ] `milk_timeline(events, period)` — ミルク回数と量の時系列棒グラフ + 3 日移動平均線
  - [ ] `sleep_timeline(events, period)` — 1 日毎の合計睡眠 (日中 / 夜間スタック)
  - [ ] `weight_height_timeline(events, period)` — 体重・身長・頭囲の折れ線 (右 Y 軸で頭囲)
  - [ ] `feeding_heatmap(events, period)` — 曜日 × 時間帯 (1 時間刻み) の授乳ヒートマップ
  - [ ] `dashboard(events, period)` — 1 枚に上記 4 種を 2x2 サブプロット集約
- [ ] テーマ: Paper Cream #FAF6F0 背景 / Deep Ink #2B2825 文字 / Peach #F4A896 / Sage #A9C4A0 / Butter #F5D680 / Sky #A4C5D8
- [ ] Noto Sans CJK JP (日本語ラベル崩れ防止)
- [ ] 出力: PNG bytes (GCS 不使用、メモリ返しから直接 LINE Content Message で送信 — Phase 1.5 はまだ GCS 連携しない)

#### LINE からのグラフ取得

- [ ] `command_router` に以下を追加 (テキストコマンドから起動):
  - `ミルク` / `milk` → milk_timeline
  - `睡眠` / `sleep` → sleep_timeline
  - `体重` / `weight` → weight_height_timeline
  - `時間帯` / `heatmap` → feeding_heatmap
  - `ダッシュボード` / `dashboard` → dashboard
- [ ] LINE Content Message で画像送信 (`ImageMessage`, `originalContentUrl` / `previewImageUrl`)
- [ ] 画像は一時公開 URL が必要。Phase 1.5 はローカル開発優先なので **ngrok 経由で `/api/line/image/{id}.png` を公開** する route を追加 (Phase 4 GCP 時に GCS Signed URL へ切替)
- [ ] 生成済み画像の TTL 管理 (メモリ LRU 50 枚 or ディスク自動削除)

#### ロールバック

- [ ] `app/services/command_router.py` に `取り消し` / `undo` コマンド追加
- [ ] `EventRepo.rollback_latest_batch(family_id) -> ImportBatch | None` を追加
  - `import_batches` テーブルの直近 `rolled_back_at IS NULL` なバッチを 1 件、`rolled_back_at = now` で更新
  - 戻り値はロールバック対象のバッチ (event_count, imported_at) → ユーザへの確認メッセージ用
- [ ] 集計クエリ (`fetch_events_in_range`) は既に `rolled_back_at IS NULL` で絞っているため SQL 追加変更なし
- [ ] ユニットテスト: rollback 直後に同 .txt を再 import できる (dedup 制約が `rolled_back_at IS NULL` 付きの partial unique なので OK)

#### テスト

- [ ] `tests/test_visualizer.py`: 各グラフ関数が PNG bytes を返すこと、ラベル文字列に期待値が含まれること (画像差分比較はしない)
- [ ] `tests/test_rollback.py`: rollback 後 count_events が減ること、再 import が成功すること
- [ ] E2E: LINE webhook → `ミルク` → 画像 push → ログに `ImageMessage` 送信が記録される

**マイルストーン**: LINE の `ミルク` / `睡眠` / `体重` / `時間帯` / `ダッシュボード` でグラフ画像が返り、`取り消し` で直近取り込みが無効化される。

---

### Phase 2: リッチメニュー (Postback)

**目標**: メニュータップだけで「今日」「ミルク」「相談」などを起動できる状態。テキストコマンドも併存 (音声入力・慣れユーザ向け)。

#### 画像生成 + LINE 登録

- [ ] `scripts/setup_richmenu.py` 新設:
  - [ ] Pillow で 2500×1686 キャンバス作成、クリーム背景・4×2 グリッド・絵文字 + 日本語ラベル
  - [ ] normal mode メニュー (📊今日 / 📈ミルク / 💤睡眠 / ⚖️体重 / 📅週間 / 🔥ヒートマップ / 💬相談 / ❓ヘルプ)
  - [ ] consulting mode メニュー (💬相談 が 🚪相談終了 に差し替え、他は共通)
  - [ ] LINE API で `/v2/bot/richmenu` 登録 → rich_menu_id を取得
  - [ ] デフォルトメニューに `setDefaultRichMenu` で登録
  - [ ] 標準出力に `RICH_MENU_ID_NORMAL=...` / `RICH_MENU_ID_CONSULTING=...` を print → ops が `.env` に反映

#### Postback ハンドラ

- [ ] `app/services/line_client.py` の DTO に `LinePostbackEvent` を追加
- [ ] `line_client.parse_events` が `PostbackEvent` も拾う
- [ ] `app/services/postback_router.py` 新設:
  - `action=summary&period=today|week` → command_router 経由で summary 実行
  - `action=chart&kind=milk|sleep|weight|heatmap|dashboard` → visualizer 経由でグラフ
  - `action=consult&op=enter|exit` → Phase 3 で実装される consulting mode 切替 (Phase 2 段階では no-op + stub)
  - `action=help` → HELP_TEXT
- [ ] `line_handler.handle_event` で `LinePostbackEvent` 分岐を追加
- [ ] 既存 `command_router` を Postback からも再利用できる形にリファクタ (サブ関数化)

#### 友だち追加時 Welcome

- [ ] `FollowEvent` を parse_events で拾う
- [ ] `handle_event` で Welcome テキスト + デフォルトメニュー紐付け
- [ ] 許可リスト外ユーザは「利用できません」と返すだけ

#### テスト

- [ ] `tests/test_postback_router.py`: action → handler 振分
- [ ] `tests/test_setup_richmenu.py`: 画像生成が失敗しない (LINE API 呼出は monkeypatch で stub)
- [ ] 実機: 2 人の LINE でメニューが表示され、タップで正しい結果が返る

**マイルストーン**: メニュータップだけでサマリとグラフが取れる。テキストコマンドも引き続き動く。

---

### Phase 3: Claude 相談機能

**目標**: `相談` ボタンから文脈依存の育児相談ができ、緊急キーワードで #8000 / 119 に誘導される。

#### Session / Conversation ストア (SQLite)

- [ ] `app/repositories/schema.sql` に追加:
  ```sql
  CREATE TABLE sessions (line_user_id TEXT PK, mode TEXT, consulting_since TEXT,
                         current_conversation_id TEXT);
  CREATE TABLE conversations (conversation_id TEXT PK, family_id TEXT, line_user_id TEXT,
                              started_at TEXT, ended_at TEXT, message_count INT,
                              summary TEXT, system_prompt_version TEXT);
  CREATE TABLE conversation_messages (message_id TEXT PK, conversation_id TEXT FK,
                                      role TEXT, content TEXT, created_at TEXT,
                                      claude_model TEXT, input_tokens INT,
                                      output_tokens INT, cache_read_tokens INT);
  ```
- [ ] `app/repositories/session_repo.py` 新設: `get_mode`, `set_mode`, `start_conversation`, `append_message`, `close_conversation`, `fetch_history(limit=20)`

#### Context Builder

- [ ] `app/services/context_builder.py` 新設:
  - [ ] 子の月齢 (BIRTH_DATE 環境変数 or `.txt` 内 age から推定)
  - [ ] 直近 72h のイベントサマリ (analytics.summarize を内部利用)
  - [ ] 直近 7 日の日次サマリ (day × type のピボット)
  - [ ] 体重 / 身長 / 体温の最新値と推移傾向
  - [ ] 直近の症状記録 (体温 >= 37.5°C の行) と投薬記録
  - [ ] 最終出力: 500〜1500 tokens の日本語テキスト 1 本

#### Emergency Gate

- [ ] `app/services/emergency_gate.py` 新設:
  - [ ] regex: `高熱|40度|39度|ひきつけ|けいれん|痙攣|呼吸(しない|苦しい|おかしい)|意識(ない|朦朧)|ぐったり|反応がない|チアノーゼ|唇が紫|大量出血|頭を打った|嘔吐(止まらない|緑|血)` 等
  - [ ] `check(text) -> EmergencyMatch | None` を返す純関数 (ユーザ文字列への依存のみ、Claude 呼ばず)
  - [ ] マッチ時の定型メッセージ: #8000 / 119 / 医師受診誘導
- [ ] `tests/test_emergency_gate.py`: 全キーワード・誤検知しないケース (「今日は元気でした」等)

#### Claude 連携

- [ ] `app/services/consultation.py` 新設:
  - [ ] SYSTEM_PROMPT 定数 (2000 tokens 程度、医療診断しない・共感的・断定避け・情報源提示)
  - [ ] `LLMClient` (lifeplanner-agent の `services.llm_client`) を遅延 import で DI
  - [ ] `complete_messages(system=SYSTEM_PROMPT, messages=[RECENT_CONTEXT_USER, ASST_ACK, ...history, user_q], cache_system=True)`
  - [ ] 20 ターン超過時は古い履歴を Claude に要約させて `conversations.summary` に格納
- [ ] prompt regression テストケース集 (`tests/test_consultation_prompts.py`):
  - [ ] 診断要求→ 診断しない旨の返答
  - [ ] 発熱相談 → #8000 誘導を含むか
  - [ ] 日常相談 → RECENT_CONTEXT に基づく具体的応答

#### リッチメニュー / モード切替

- [ ] `相談 / consult` コマンド / Postback `action=consult&op=enter` で:
  - [ ] `sessions.mode = "consulting"` に更新
  - [ ] `linkRichMenuIdToUser` で consulting menu に切替
  - [ ] 開始メッセージ返信 (#8000 / 119 を添える)
- [ ] `相談終了 / exit` / `op=exit` で normal に戻す
- [ ] consulting mode 中のテキストメッセージ:
  - [ ] まず emergency_gate
  - [ ] 通らなければ `consultation.reply` を呼び結果を返信
  - [ ] 全ターン Firestore ではなく SQLite に保存

#### セキュリティ・コスト管理

- [ ] userId はコンテキストに入れない (Claude に流さない)
- [ ] 1 セッション単位のトークン超過監視 (`conversations.message_count` > 40 で警告)
- [ ] Anthropic API Key は `.env` / 本番は Secret Manager

#### テスト

- [ ] `tests/test_session_repo.py`
- [ ] `tests/test_context_builder.py`: ダミーイベントから期待コンテキスト生成
- [ ] `tests/test_consultation.py`: Mock LLMClient で end-to-end (history + cache_system の引数を検証)
- [ ] 実機 dogfooding 2 週間 → プロンプト調整

**マイルストーン**: 「相談」ボタンから文脈依存の育児相談ができ、緊急キーワードで #8000 に誘導される状態。

---

### 複数子対応 (将来)

Phase 1 は `child_id` を `DEFAULT_CHILD_ID` 固定。
複数子の場合は、Phase 2+ で `.txt` 内の名前 (`baby_name` パース済) から自動判定 or
`期間 さくら 2026-04-22 2026-04-22` のような指定を導入予定。

---

## 7. 監視・運用

| 症状 | 確認ポイント |
|---|---|
| 署名検証 401 | `LINE_CHANNEL_SECRET` と LINE Developers Console の Channel secret 一致確認 |
| 503 応答 | `.env` に LINE 認証情報が設定されているか、プロセス再起動後に反映されたか |
| 応答が返らない | `FAMILY_USER_IDS` に自分の LINE userId が入っているか (LINE Developers の userId は webhook ログから確認) |
| 取り込み時 `InvalidPiyologFileError` | ぴよログアプリから export した .txt をそのまま送信しているか (UTF-8 / cp932 自動判定) |
| サマリが空 | `event_date` (JST) と指定期間が一致しているか、`import_batches.rolled_back_at IS NULL` か |

データ確認クエリ:

```bash
sqlite3 data/piyolog.db "SELECT event_date, event_type, COUNT(*) FROM piyolog_events GROUP BY 1, 2 ORDER BY 1 DESC LIMIT 20;"
```
