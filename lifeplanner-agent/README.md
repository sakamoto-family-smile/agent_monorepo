# ライフプランナーエージェント (lifeplanner-agent)

Money Forward ME の家計データを起点に、家族単位のライフプランニング・長期シミュレーション・ライフイベント（出産・住宅購入・車買替等）ごとの費用増加検討を、対話型 AI エージェントで支援するシステム。

> **Status**: Phase 4 進行中 (LINE 操作の拡充 + Phase 5 計画は [`docs/DESIGN.md §6`](docs/DESIGN.md))
>
> 設計書 / 機能要件 / 非機能要件 / アーキテクチャは [`docs/DESIGN.md`](docs/DESIGN.md) を参照。

---

## 0. Quickstart

### 0.1 前提ツール

| ツール | バージョン | 備考 |
|---|---|---|
| Python | 3.12+ | `pyproject.toml` で指定 |
| uv | 最新 | パッケージ管理 (`curl -LsSf https://astral.sh/uv/install.sh \| sh`) |
| Docker / Docker Compose | 任意 | `docker compose up` で一括起動する場合のみ |
| gcloud CLI | 任意 | `LLM_PROVIDER=vertex` で ADC を使う場合 |

### 0.2 初期セットアップ

```bash
cd agent_monorepo/lifeplanner-agent

# 1. 環境変数テンプレートをコピー
cp .env.example .env
# → .env を編集して必要なキーを設定 (最低限は何も設定しなくても LLM_MOCK_MODE=true で起動可)

# 2. 依存インストール (dev 含む)
make install

# 3. ローカル SQLite を使う場合、起動時に自動で DB 初期化されるためマイグレーション不要
#    Postgres を使う場合のみ:
#    DB_URL=postgresql+asyncpg://... uv run alembic upgrade head

# 4. MF ME CSV を配置 (任意、Phase 1+ の /api/upload で使用)
mkdir -p data/mf_csv
cp ~/Downloads/収入・支出詳細_*.csv data/mf_csv/
```

### 0.3 起動

```bash
# ローカル (FastAPI のみ、SQLite)
make run                 # → http://127.0.0.1:8001

# または Docker Compose (ホットリロード付き)
docker compose up --build    # → http://127.0.0.1:8001

# ヘルスチェック
curl http://127.0.0.1:8001/health
# → {"status":"ok","service":"lifeplanner-agent"}

# OpenAPI ドキュメント (Swagger UI)
open http://127.0.0.1:8001/docs
```

### 0.4 テスト・静的解析

```bash
make test         # pytest
make lint         # ruff check
make format       # ruff format + --fix
make check        # lint + test
```

### 0.5 主要 API エンドポイント

すべて `X-Household-ID` ヘッダで世帯を指定（未指定時は `DEV_HOUSEHOLD_ID` フォールバック）。

| メソッド | パス | 用途 |
|---|---|---|
| `POST` | `/api/upload` | MF ME CSV をアップロードして取り込み |
| `GET` | `/api/transactions` | 取引一覧（期間・カテゴリでフィルタ） |
| `GET` | `/api/summary` | 月次サマリ（収入・支出・カテゴリ別） |
| `GET` | `/api/networth` | 純資産スナップショット |
| `GET` | `/api/anomalies` | 異常値検知（外れ値の取引） |
| `GET/POST/DELETE` | `/api/profile/members` | 世帯メンバー管理 |
| `GET/POST/DELETE` | `/api/profile/assets` | 資産管理 |
| `GET/POST/DELETE` | `/api/profile/liabilities` | 負債管理 |
| `GET/POST` | `/api/scenarios` | シナリオ一覧 / 作成 |
| `POST` | `/api/scenarios/{id}/events` | シナリオにライフイベント追加 |
| `POST` | `/api/scenarios/{id}/simulate` | 30年プロジェクション実行 |
| `POST` | `/api/scenarios/compare` | 複数シナリオの決定論的差分 |
| `POST` | `/api/chat` | LLM アドバイザー（シナリオ要約・比較解説） |
| `POST` | `/api/line/webhook` | **LINE Bot Webhook** (LINE Messaging API からのコールバック) |
| `GET` | `/liff/link.html` | **LIFF ページ** (LINE Login → ID トークンを POST) |
| `POST` | `/api/line/liff-login` | LIFF から受けた ID トークンを検証して世帯連携 |

#### 使い方例

```bash
# MF CSV アップロード
curl -X POST http://127.0.0.1:8001/api/upload \
  -H "X-Household-ID: dev-household-00000000" \
  -F "file=@data/mf_csv/収入・支出詳細_2026-04.csv"

# 期間サマリ (start / end は YYYY-MM-DD、省略時は当月)
curl "http://127.0.0.1:8001/api/summary?start=2026-04-01&end=2026-04-30" \
  -H "X-Household-ID: dev-household-00000000"

# シナリオ作成 (primary_salary / start_year は必須)
curl -X POST http://127.0.0.1:8001/api/scenarios \
  -H "X-Household-ID: dev-household-00000000" \
  -H "Content-Type: application/json" \
  -d '{
        "name": "base",
        "description": "現状維持",
        "primary_salary": 6000000,
        "start_year": 2026,
        "horizon_years": 30
      }'

# 30年プロジェクション実行
curl -X POST http://127.0.0.1:8001/api/scenarios/1/simulate \
  -H "X-Household-ID: dev-household-00000000"

# LLM 要約（LLM_MOCK_MODE=true 時は決定論モック応答）
curl -X POST http://127.0.0.1:8001/api/chat \
  -H "X-Household-ID: dev-household-00000000" \
  -H "Content-Type: application/json" \
  -d '{"scenario_ids":[1,2],"question":"どちらが有利？"}'
```

### 0.6 環境変数サマリ

主要なもののみ。詳細は `.env.example` 参照。

| 変数 | 既定 | 用途 |
|---|---|---|
| `APP_ENV` | `local` | `local` 以外で SQLite 自動作成を無効化 |
| `LOG_LEVEL` | `info` | ログレベル |
| `DB_URL` | `sqlite+aiosqlite:///data/lifeplanner.db` | DB 接続文字列 |
| `MF_CSV_DIR` | `data/mf_csv` | CSV 配置先 (gitignore 済) |
| `DEV_HOUSEHOLD_ID` | `dev-household-00000000` | 認証スタブ用フォールバック |
| `LLM_PROVIDER` | `anthropic` | `anthropic` \| `vertex` |
| `LLM_MODEL` | `claude-sonnet-4-6` | モデル名 (Vertex は `@日付` 付き) |
| `LLM_MAX_TOKENS` | `1200` | レスポンス上限 |
| `LLM_MOCK_MODE` | `false` | `true` で LLM をモック化（オフライン開発） |
| `ANTHROPIC_API_KEY` | - | `LLM_PROVIDER=anthropic` で必須 |
| `GOOGLE_CLOUD_PROJECT` / `VERTEX_AI_LOCATION` | - / `us-east5` | `LLM_PROVIDER=vertex` で必須 |
| `LINE_CHANNEL_SECRET` | - | LINE Bot 署名検証用チャネルシークレット (未設定なら `/api/line/webhook` が 503) |
| `LINE_CHANNEL_ACCESS_TOKEN` | - | LINE Messaging API 呼出用トークン (同上、Rich menu セットアップにも利用) |
| `LIFF_ID` | - | LIFF アプリ ID (`12345-abcdefg` 形式)。未設定なら `/liff/link.html` と `/api/line/liff-login` が 503 |
| `LINE_LOGIN_CHANNEL_ID` | - | LINE Login チャネル ID (ID トークンの `aud` 検証用)。`/api/line/liff-login` 必須 |
| `ANALYTICS_ENABLED` | `true` | `false` で analytics-platform への送信を無効化 (NoOpSink) |
| `ANALYTICS_DATA_DIR` | `./data/analytics` | 業務ログ JSONL の出力先 |
| `ANALYTICS_SERVICE_NAME` | `lifeplanner-agent` | service_name (Hive パーティションキー) |
| `ANALYTICS_COMPRESS` | `false` | JSONL を gzip するか |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | - | Phoenix / Langfuse OTLP HTTP endpoint (未設定時は span 未送信、業務ログは出る) |
| `OTEL_SAMPLING_RATIO` | `1.0` | OTel サンプリング率 0.0〜1.0 |
| `ANALYTICS_STORAGE_BACKEND` | `local` | `gcs` で Cloud Run + Workload Identity 経由 GCS 連携 (Phase 5 Step 10) |
| `ANALYTICS_GCS_BUCKET` | - | `gcs` backend 時必須。`analytics-platform/terraform` の `raw_bucket` 出力値 |
| `ANALYTICS_GCS_RAW_PREFIX` | `uploaded/` | `gcs` backend 時の raw JSONL prefix |
| `ANALYTICS_GCS_PAYLOAD_PREFIX` | `payloads/` | `gcs` backend 時の大容量 payload prefix |
| `ANALYTICS_GCP_PROJECT` | (ADC から自動推論) | `gcs` backend 時の GCP project id (Workload Identity なら省略可) |
| `ANALYTICS_UPLOAD_INTERVAL_SECONDS` | `300` | 周期 upload 間隔。0 以下なら shutdown 時のみ upload |

### 0.7 LINE Bot セットアップ (Phase 3b)

1. **LINE Developers コンソール** で Messaging API チャネルを作成し、
   - `Channel secret` → `LINE_CHANNEL_SECRET`
   - `Channel access token` (長期) → `LINE_CHANNEL_ACCESS_TOKEN`
2. `.env` に上記 2 つを設定してアプリを起動
3. ローカルで動作確認する場合は ngrok 等で公開 URL を作り、
   `https://<public>/api/line/webhook` を LINE Webhook URL に登録
4. 友だち追加後に bot に何か送ると世帯が自動作成され、以降は下記コマンドが利用可能

| コマンド | 動作 |
|---|---|
| (任意テキスト) | 初回は世帯自動作成、以降は `/help` を案内 |
| `/help` | コマンド一覧 |
| `/whoami` | 連携状態と世帯 ID を表示 |
| `/invite` | 配偶者共有用の `/link <世帯ID>` コマンドを出力 |
| `/link <世帯ID>` | 既存世帯へ参加 |
| `/unlink` | 連携解除 |
| `/scenarios` | シナリオ一覧 |
| `/summarize <id>` | 単一シナリオの LLM 要約 |
| `/compare <id1> <id2> [...]` | シナリオ比較 (最大5件) |
| `/summary [今月\|先月\|今年\|YYYY-MM YYYY-MM]` | 月次サマリ (Phase 4 / PR 2) |
| `/networth [YYYY-MM-DD]` | 純資産 + 種別別内訳 (Phase 4 / PR 2) |
| `/anomalies [YYYY-MM]` | 3σ 異常検知 (Phase 4 / PR 2) |
| CSV ファイル送信 | 世帯に取り込み (MF ME CSV, 5MB まで) |

### 0.8 LIFF セットアップ (Phase 3b.2)

1. **LINE Developers** で LIFF アプリを作成:
   - Scope: `profile` + `openid` (ID トークン取得に openid が必須)
   - Endpoint URL: `https://<public-host>/liff/link.html`
   - `LIFF ID` を `.env` の `LIFF_ID` に設定
2. **LINE Login チャネル** の Channel ID を `.env` の `LINE_LOGIN_CHANNEL_ID` に設定 (ID トークンの `aud` クレーム検証に使用)
3. LIFF URL (`https://liff.line.me/<LIFF_ID>`) をユーザーに配布するか、Rich menu の「連携」ボタンに紐付ける
4. ユーザーが LIFF を開くと:
   - `liff.login()` でログイン (未ログイン時のみ)
   - `liff.getIDToken()` で ID トークン取得
   - `POST /api/line/liff-login` に送信 → 自動で世帯作成 or 指定世帯へ紐付け
   - 以降は LINE Webhook 経由でコマンドが利用可能

### 0.9 Flex Message / Rich menu

- **Flex Message**: `/scenarios` は Carousel、`/summarize` と `/compare` / `/summary` / `/networth` / `/anomalies` は Bubble で返す。
  SDK 未対応クライアントや Flex 構築失敗時は自動で plain text にフォールバックする。
- **Rich menu 登録** (1 回のセットアップ):
  ```bash
  # ドライラン (API 不要、JSON + PNG を logs/ に書き出す)
  uv run python scripts/setup_rich_menu.py --dry-run
  # 本番登録 (LINE_CHANNEL_ACCESS_TOKEN / LIFF_ID を env に設定した上で)
  uv run python scripts/setup_rich_menu.py
  ```
  ボタン構成 (PR 2 で 6 ボタンに拡張、2500x1686):
  ```
  ┌─────────────────────────────────────────┐
  │ 📊 サマリ   💰 純資産   ⚠️ 異常検知   │
  ├─────────────────────────────────────────┤
  │ 📋 シナリオ  💬 連携    ❓ ヘルプ      │
  └─────────────────────────────────────────┘
  ```
  「連携」は `LIFF_ID` が設定されていれば LIFF URL、未設定時は `/help` コマンドにフォールバック。
  カラー絵文字は Apple Color Emoji / Noto Color Emoji を自動検出。

### Phase 3b 未対応 (Phase 4 予定)

- push 通知 / リマインダー (月次 CSV 取込忘れ・ライフイベント接近)
- Flex Message のインタラクティブコンポーネント (datetime picker, postback 等)
- LIFF からの CSV アップロード UI (現状は LINE のファイル添付のみ)

---

## 0.10 分析基盤 (analytics-platform) への送信情報

このエージェントは [`../analytics-platform`](../analytics-platform/) に対して、業務イベントを JSONL として書き出します。`ANALYTICS_DATA_DIR/raw/service_name=lifeplanner-agent/event_type=*/dt=YYYY-MM-DD/hour=HH/*.jsonl` に Hive パーティション形式で蓄積されます。

### 送信されるイベント種別と発火タイミング

| event_type | 発火タイミング | 主要フィールド |
|---|---|---|
| `business_event` (action=`scenario_created`) | `POST /api/scenarios` 成功時 | `name` / `has_description` |
| `business_event` (action=`scenario_simulated`) | `POST /api/scenarios/{id}/simulate` 成功時 | `horizon_years` / `total_net_worth_end` / `total_take_home` |
| `business_event` (action=`chat_completed`) | `POST /api/chat` 成功時 | `intent` / `scenario_count` / `narrative_chars` / `had_question` |
| `business_event` (action=`csv_imported`) | `POST /api/upload` 成功時 | `encoding` / `imported` / `inserted` / `updated` / `skipped_*` |
| `business_event` (action=`webhook_processed`) | `POST /api/line/webhook` 完了時 | `received` / `handled` / `failed` |
| `business_event` (action=`liff_login`) | `POST /api/line/liff-login` 成功時 | `created` / `already_linked` |
| `llm_call` | `AnthropicLLMClient.complete` / `VertexAnthropicLLMClient.complete` ごと | `llm_provider` / `llm_model` / `input_tokens` / `output_tokens` / `cache_read_tokens` / `latency_ms` |
| `error_event` | route 内バリデーション失敗 / LINE handler 例外時 | `error_type` / `error_message` / `error_category` |

### 各イベントに共通のフィールド

すべて [`analytics_platform.observability.schemas`](../analytics-platform/analytics_platform/observability/schemas.py) で Pydantic 検証されます。共通: `event_id` / `event_timestamp` / `service_name` / `service_version` / `environment` / `trace_id` / `span_id` / `user_id` (= `household_id`) / `session_id` / `severity`。

### 送信されない情報 (プライバシー / コスト配慮)

- **ユーザー入力テキスト本体** (チャット質問文、CSV の取引内容など): 件数・件名・要約のみで、生データは送らない
- **API キー / OAuth トークン**: 一切送らない
- **LLM の raw prompt / response**: `llm_call` イベントには含めない (内訳が必要な時は OTel + Phoenix を立てて span 側で確認する)

### 突合キー

`user_id = household_id` でユーザー / 世帯軸の集計が可能。OTLP endpoint を設定して Phoenix / Langfuse を立てた場合は `trace_id` も入り、LLM トレース側との突合も可能になります。

### 動作モード切替

| `ANALYTICS_ENABLED` | 挙動 |
|---|---|
| `true` (既定) | `RotatingFileSink` で JSONL を書き出す |
| `false` | `NoOpSink` に置換、JSONL は一切書かれない (テスト用 / 緊急遮断用) |

### ローカル / GCP backend 切替 (Phase 5 Step 10)

| `ANALYTICS_STORAGE_BACKEND` | 挙動 |
|---|---|
| `local` (既定) | JSONL は `ANALYTICS_DATA_DIR/raw/` に書かれ、`LocalUploader` が定期的に `uploaded/` へ move |
| `gcs` | JSONL は同じく local FS にバッファされた後、`LocalUploader` が `GCSTransport` で `gs://${ANALYTICS_GCS_BUCKET}/${ANALYTICS_GCS_RAW_PREFIX}` に upload。大容量 payload も `GCSPayloadWriter` で直接 GCS に書く |

`gcs` 切替に必要なコード変更はゼロ。`.env` (Cloud Run なら環境変数) で:

```bash
ANALYTICS_STORAGE_BACKEND=gcs
ANALYTICS_GCS_BUCKET=analytics-raw           # terraform output raw_bucket
ANALYTICS_GCP_PROJECT=your-gcp-project       # 省略時 ADC から推論
ANALYTICS_GCS_RAW_PREFIX=uploaded/
ANALYTICS_GCS_PAYLOAD_PREFIX=payloads/
ANALYTICS_UPLOAD_INTERVAL_SECONDS=300
```

#### Cloud Run + Workload Identity デプロイ手順

```bash
# 1. analytics-platform 側で TF apply 済 + sa-uploader が作られている前提
SA="sa-uploader@${PROJECT}.iam.gserviceaccount.com"

# 2. Cloud Run service にこの SA を紐付ける
gcloud run services update lifeplanner-agent \
  --region=us-central1 --service-account="${SA}"

# 3. env を反映 (terraform output env_for_dotenv の値を流用)
gcloud run services update lifeplanner-agent --region=us-central1 \
  --update-env-vars=ANALYTICS_STORAGE_BACKEND=gcs,ANALYTICS_GCS_BUCKET=analytics-raw,ANALYTICS_GCP_PROJECT=${PROJECT}

# 4. 動作確認
#   - Cloud Logging で `[upload] cycle: uploaded=N` ログ
#   - GCS bucket に uploaded/service_name=lifeplanner-agent/... が増える
#   - BQ: SELECT COUNT(*) FROM analytics_raw.agent_events_external WHERE service_name='lifeplanner-agent'
```

`sa-uploader` には `analytics-platform/terraform/iam.tf` で raw / payloads / dead_letter bucket への `objectAdmin` が事前に紐付いている。

### 実機検証スクリプト

```bash
# 主要 API を ASGI 経由で叩いて JSONL が書かれるか検証 (デフォルトは LLM_MOCK_MODE=true)
uv run python scripts/integration_check_observability.py
# → data/_integration_check/raw/ 配下に event_type 別 JSONL が生成され、
#    末尾に件数サマリ + PASS/FAIL を表示

# 実 LLM (Anthropic) も呼んで llm_call イベントを確認したい場合
LLM_MOCK_MODE=false ANTHROPIC_API_KEY=sk-... \
  uv run python scripts/integration_check_observability.py
```

実行例 (MOCK モード、約 1 秒):
```
event_type counts:
  business_event          : 4
business_event actions: ['chat_completed', 'csv_imported', 'scenario_created', 'scenario_simulated']
PASS: 主要 4 アクション (...) 確認
```

---

## 1. 関連ドキュメント

このエージェントの設計や進行中の Phase 4 ロードマップは別ファイルに分離している:

- [`docs/DESIGN.md`](docs/DESIGN.md) — システム全体設計書 (機能要件 F1〜F12 / 非機能要件 / アーキテクチャ / Roadmap / 設計判断ログ / セキュリティ / テスト戦略)
- [`docs/LINE_ROADMAP.md`](docs/LINE_ROADMAP.md) — Phase 4 の LINE 拡充 (PR 単位の中粒度ロードマップ)
- [`../docs/PROPOSALS/`](../docs/PROPOSALS/) — モノレポ共通の機能個別 ADR
  - [`0001-lifeplanner-cashflow-breakdown.md`](../docs/PROPOSALS/0001-lifeplanner-cashflow-breakdown.md) — PR #103 のバックエンド粒度向上
- [モノレポ全体の設計テンプレート](../docs/) — `SYSTEM_DESIGN_TEMPLATE.md` / `README_TEMPLATE.md` / `PROPOSALS/TEMPLATE.md`

## 2. 免責

本システムの出力は参考値であり、税務・投資・法務の正式な助言ではない。個別の重要判断は税理士・ファイナンシャルプランナー等の専門家に相談すること。
