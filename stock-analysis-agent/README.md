# 株価分析エージェント (Stock Analysis Agent)

日本株・米国株を対象とした AI 駆動の株価分析システム。Claude Opus（VertexAI 経由）を活用し、テクニカル分析・ファンダメンタル分析・センチメント分析を統合した日本語レポートを生成します。

---

## 要件定義

### 概要

| 項目 | 内容 |
|------|------|
| 対象市場 | 日本株（東証）・米国株（NASDAQ/NYSE） |
| 分析対象 | 日次 OHLCV、テクニカル指標、ファンダメンタルズ、センチメント |
| 入力形式 | 企業名（例: "トヨタ"）またはティッカー（例: "7203.T", "AAPL"） |
| 出力形式 | 日本語分析レポート（テキスト + チャート画像） |
| LLM | Claude Opus (claude-opus-4-6) via VertexAI |
| 動作環境 | ローカル（SQLite + ローカルファイルシステム） |

---

### ティッカー解決（4ステップフォールバック）

企業名から銘柄コードへの変換を以下の順で試行します。

```
Step 1: 正規表現チェック
  → すでにティッカー形式（AAPL, 7203.T）の場合はそのまま使用

Step 2: ローカル辞書（SQLite）
  → 登録済み企業名・別名から照合

Step 3: yfinance Search API
  → yfinance を使ってオンライン検索

Step 4: Claude LLM フォールバック
  → 上記で解決できない場合、低信頼度で返却
```

**ResolveResult モデル**:

```python
class ResolveResult(BaseModel):
    ticker: str
    confidence: float   # 0.0 〜 1.0
    source: str         # "regex" | "dict" | "yfinance" | "llm"
    company_name: Optional[str]
```

---

### データ収集

| データ種別 | ソース | キャッシュ |
|-----------|--------|-----------|
| 日次 OHLCV | yfinance | SQLite（TTL: 24時間） |
| ファンダメンタルズ | yfinance `.info` | なし（都度取得） |
| ニュース・センチメント | Brave Search MCP | なし |

---

### テクニカル指標

pandas を使って計算（pandas-ta は使用せず純 pandas 実装）:

| 指標 | パラメータ |
|------|-----------|
| SMA | 20日・50日 |
| EMA | 20日 |
| RSI | 14日 |
| MACD | 12-26-9 |
| ボリンジャーバンド | 20日・2σ |

---

### 分析フロー

```
ユーザー入力（企業名 or ティッカー）
  ↓
1. ティッカー解決（4ステップ）
  ↓
2. データ収集（並列）
   ├─ OHLCV データ取得（yfinance）
   └─ ファンダメンタルズ取得（yfinance）
  ↓
3. テクニカル指標計算（pandas）
  ↓
4. チャート生成（mplfinance）
  ↓
5. Claude Opus による分析レポート生成（SSE ストリーミング）
   └─ Brave Search MCP でニュース検索・センチメント分析
  ↓
6. レポート保存（SQLite）
  ↓
結果返却（SSE ストリーム）
```

---

### 投資判断（購入推奨）

レポート末尾に固定書式の「## 投資判断」セクションを出力させ、orchestrator が構造化して `AnalysisReport.recommendation`（`BuyRecommendation`）に格納します。

| 項目 | 内容 |
|------|------|
| 判定 | `買い検討`（buy_candidate）/ `様子見`（hold）/ `見送り`（avoid）の 3 段階 |
| 根拠 | テクニカル / ファンダメンタル / センチメント別の箇条書き |
| 反対シナリオ | 判定が外れるケースの明示 |
| 免責文 | 必須（`BUY_RECOMMENDATION_DISCLAIMER`。投信ランキング・価格予測と同方針） |

- LINE 配信では要約 Flex 冒頭に判定バッジ（🟢 買い検討 / 🟡 様子見 / 🔴 見送り）+ 根拠 + 免責文を表示
- LLM 出力が書式から外れた場合は `recommendation = None` として従来の自由テキストのみにフォールバック（分析全体は失敗しない）
- 断定的な売買指示ではなく情報提供のみを目的とした 3 段階の検討度合いにとどめる

---

### DB スキーマ（SQLite）

```sql
-- ティッカー辞書
CREATE TABLE ticker_dictionary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    ticker TEXT NOT NULL,
    aliases TEXT DEFAULT '[]',
    market TEXT DEFAULT 'unknown',
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(company_name, ticker)
);

-- 価格キャッシュ
CREATE TABLE price_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    period TEXT NOT NULL,
    data TEXT NOT NULL,
    cached_at TEXT,
    expires_at TEXT NOT NULL,
    UNIQUE(ticker, period)
);

-- 分析レポート
CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    company_name TEXT,
    report_data TEXT NOT NULL,
    created_at TEXT
);

-- アラート（将来拡張用）
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    condition_data TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT
);
```

---

### API エンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/health` | ヘルスチェック |
| POST | `/api/analyze` | 株価分析実行（SSE ストリーム） |
| POST | `/api/resolve-ticker` | 企業名→ティッカー変換 |
| GET | `/api/reports/{ticker}` | 過去レポート一覧 |
| POST | `/api/screen` | 短期上昇候補スクリーニング |
| POST | `/api/funds/recommend` | 投資信託 (ETF) のオススメランキング |
| POST | `/api/line/webhook` | LINE Messaging API Webhook 受信 |

**POST /api/analyze リクエスト**:

```json
{
  "query": "トヨタ",
  "analysis_types": ["technical", "fundamental", "sentiment"],
  "period": "3mo"
}
```

**POST /api/funds/recommend リクエスト**:

```json
{
  "category": "us_index",
  "horizon": "1y",
  "top_n": 5,
  "require_uptrend": false
}
```

| フィールド | 説明 |
|---|---|
| `category` | `us_index` / `global` / `dividend` / `sector` / `all` |
| `horizon` | トレンド評価期間: `3mo` / `6mo` / `1y` / `3y` |
| `top_n` | 上位何件返すか（最大 20） |
| `require_uptrend` | `true` なら SMA50 > SMA200 (ゴールデンクロス継続) を必須化 |

レスポンスは `candidates[]` がスコア降順にランキングされ、各候補に `rationale[]`（根拠ポイント）と `disclaimer`（情報提供のみである旨）が付与されます。

> **対応範囲**: 第一段は yfinance で取得可能な ETF に限定（VOO / SPY / VTI / QQQ / VT / SCHD / SOXX 等）。日本投資信託（eMAXIS Slim 米国株式 等）は対応する米国 ETF のエイリアスとして近似しています（基準価額の直接取得は将来検討）。

---

### プロジェクト構成

```
stock-analysis-agent/
├── app/
│   ├── main.py               # FastAPI アプリ
│   ├── config.py             # 設定
│   ├── agents/
│   │   ├── orchestrator.py   # 分析パイプライン統括
│   │   ├── ticker_resolver.py  # 4ステップティッカー解決
│   │   ├── data_collection.py  # yfinance データ取得
│   │   ├── technical_analysis.py # テクニカル指標計算
│   │   └── chart_generator.py  # チャート生成
│   ├── models/
│   │   └── stock.py          # Pydantic モデル
│   ├── routes/
│   │   ├── analysis.py       # /api/analyze, /api/resolve-ticker
│   │   └── reports.py        # /api/reports/{ticker}
│   └── services/
│       └── database.py       # SQLite 操作
├── tests/
│   ├── test_health.py
│   ├── test_ticker_resolver.py
│   └── test_technical_analysis.py
├── data/                     # ローカルデータ（.gitignore）
│   ├── charts/
│   ├── cache/
│   ├── reports/
│   └── dictionaries/
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── pyproject.toml
└── .env.example
```

---

### 環境変数

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `CLAUDE_CODE_OAUTH_TOKEN` | ✅ | Claude Code OAuth トークン |
| `BRAVE_API_KEY` | - | センチメント分析用（省略可） |
| `GOOGLE_CLOUD_PROJECT` | - | VertexAI 用 GCP プロジェクト ID |
| `VERTEX_AI_LOCATION` | - | VertexAI リージョン（デフォルト: us-east5） |
| `MCP_PROXY_URL` | - | セキュリティプラットフォーム MCP プロキシ URL |
| `APP_ENV` | - | 実行環境（デフォルト: local） |
| `DB_PATH` | - | SQLite DB パス（デフォルト: data/stock_analysis.db） |
| `ANALYTICS_ENABLED` | - | `false` で分析基盤への送信を無効化（デフォルト: true） |
| `ANALYTICS_DATA_DIR` | - | 業務ログ JSONL の出力先（デフォルト: `./data/analytics`） |
| `ANALYTICS_SERVICE_NAME` | - | service_name（Hive パーティションキー、デフォルト: `stock-analysis-agent`） |
| `ANALYTICS_COMPRESS` | - | JSONL を gzip するか（デフォルト: false） |
| `ANALYTICS_CONTENT_INLINE_THRESHOLD_BYTES` | - | コンテンツ inline / URI 振り分け閾値（デフォルト: 8192） |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | - | Phoenix / Langfuse OTLP HTTP エンドポイント（未設定時は span を export しない） |
| `OTEL_EXPORTER_OTLP_HEADERS` | - | OTLP 認証ヘッダ（`k1=v1,k2=v2` 形式） |
| `OTEL_SAMPLING_RATIO` | - | OTel サンプリング率 0.0〜1.0（デフォルト: 1.0、業務ログは常に 100%） |
| `ANALYTICS_STORAGE_BACKEND` | - | `local` (既定) または `gcs`。Phase 5 Step 10 で導入、`gcs` で Cloud Run + Workload Identity 経由 GCS 連携 |
| `ANALYTICS_GCS_BUCKET` | - | `gcs` backend 時必須。`analytics-platform/terraform` の `raw_bucket` の出力値 |
| `ANALYTICS_GCS_RAW_PREFIX` | `uploaded/` | `gcs` backend 時の raw JSONL prefix |
| `ANALYTICS_GCS_PAYLOAD_PREFIX` | `payloads/` | `gcs` backend 時の大容量 payload prefix |
| `ANALYTICS_GCP_PROJECT` | (ADC から自動推論) | `gcs` backend 時の GCP project id。Cloud Run + Workload Identity なら省略可 |
| `ANALYTICS_UPLOAD_INTERVAL_SECONDS` | `300` | 周期 upload 間隔。0 以下なら shutdown 時のみ upload |
| `LINE_CHANNEL_SECRET` | - | LINE Messaging API のチャネルシークレット（未設定時 `/api/line/webhook` は 503） |
| `LINE_CHANNEL_ACCESS_TOKEN` | - | LINE Messaging API のチャネルアクセストークン（未設定時 `/api/line/webhook` は 503） |

---

## 分析基盤 (analytics-platform) への送信情報

このエージェントは [`../analytics-platform`](../analytics-platform/) に対して、リクエスト 1 本ごとに以下のイベントを送信します。

- **本番 (`ANALYTICS_STORAGE_BACKEND=pubsub`)**: イベント行を Pub/Sub topic
  (`sakamomo-family-agent-analytics-events`) に publish → Cloud Storage サブスクが
  `gs://...-analytics-raw/events/` に NDJSON で蓄積 → **BigQuery external table
  (`analytics_raw.agent_events_external`) で SQL 集計可能** (PROPOSAL-0010/0011)
- **dev (`local`、既定)**: `ANALYTICS_DATA_DIR/raw/service_name=.../event_type=*/dt=*/hour=*/*.jsonl`
  に Hive パーティション形式の JSONL として書き出し

### 送信されるイベント種別と発火タイミング

| event_type | 発火タイミング | 1 リクエストあたりの典型件数 |
|---|---|---|
| `conversation_event` | リクエスト開始時 (`started`)、正常終了時 (`ended`)、例外時 (`aborted`) | 2 |
| `business_event` (action=`ticker_resolved`) | ticker 解決完了時 | 1 |
| `business_event` (action=`claude_query_completed`) | Claude Agent SDK の `ResultMessage` 受信時 | 1 |
| `business_event` (action=`report_saved`) | 分析レポート DB 保存完了時 | 1 |
| `business_event` (action=`funds_recommended`) | `/api/funds/recommend` 完了時 | 0 or 1 |
| `business_event` (action=`line_webhook_processed`) | `/api/line/webhook` 受信完了時 | 0 or 1 |
| `llm_call` | Claude SDK の `AssistantMessage` 受信ごと | 数十 (turn 数依存) |
| `tool_invocation` | MCP ツール (`brave-search` 等) の結果受信ごと | 0〜数十 |
| `message` | アシスタントの本文 `TextBlock` ごと | 数件 |
| `error_event` | orchestrator 内で例外発生時 | 0 or 1 |

### 各イベントに含まれる主要フィールド

すべて [`analytics_platform.observability.schemas`](../analytics-platform/analytics_platform/observability/schemas.py) で Pydantic 検証されます。共通フィールド (`event_id` / `event_timestamp` / `service_name` / `service_version` / `environment` / `trace_id` / `span_id` / `user_id` / `session_id` / `severity`) に加え、種別ごとに以下が付与されます。

> **`user_id` (LINE userId)**: ユーザー別の利用統計 (誰が何回分析したか等) のため、
> webhook / worker の入口で contextvar に設定され全イベントに付与される。LINE userId
> は provider 固有の仮名 ID であり、allow-list 運用 (家族のみ) の本サービスでは
> 管理者が対応関係を把握している前提で生値を保持する。

#### `llm_call` — Claude Agent SDK の AssistantMessage ごと
- `llm_provider` = `"anthropic"`
- `llm_model` (例: `claude-opus-4-6`)
- `input_tokens` / `output_tokens` / `cache_read_tokens` / `cache_creation_tokens`
- `stop_reason`

#### `tool_invocation` — MCP ツール / built-in ツールの結果ごと
- `tool_name` (例: `mcp__brave-search__search`, `Read`, `Grep`)
- `duration_ms` (ToolUseBlock 受信時刻 → ToolResultBlock 受信時刻の差)
- `status` = `success` / `error`
- `output_size_bytes`
- `retry_count`

#### `message` — assistant 応答テキストごと
- `message_id` / `message_role` = `"assistant"` / `message_index`
- `content_inline` (8KB 以下は本文をイベントに内包) **または** `content_uri` (8KB 超は payload として退避し URI 参照。`ANALYTICS_GCS_BUCKET` 設定時 = 本番は `gs://...-analytics-payloads/` に永続化、未設定時はローカル `file://` で揮発)
- `content_hash` (`sha256:<hex>`)
- `content_preview` (先頭 500 文字)
- `content_size_bytes` / `content_truncated`

#### `business_event` — ドメインアクション
- `business_domain` = `"stock_analysis"`
- `action` = `ticker_resolved` / `claude_query_completed` / `report_saved` / `funds_recommended` / `line_webhook_processed`
- `resource_type` / `resource_id`
- `attributes` (アクション固有の付帯情報、例: `ticker_resolved` には `company_name` / `confidence` / `source`、`funds_recommended` には `category` / `horizon` / `top_n` / `top_tickers`、`line_webhook_processed` には `received` / `handled` / `failed`)

#### `conversation_event` — リクエストライフサイクル
- `conversation_phase` = `started` / `ended` / `aborted`
- `agent_id` = service_name
- `initial_query_hash` (`sha256:<hex>`、ユーザー入力の生文字列は保存しない)

#### `error_event` — 例外発生時
- `error_type` (例: `RuntimeError` / `TimeoutError`)
- `error_message` (1000 文字まで切詰)
- `error_category` = `internal`
- `is_retriable`

### 送信されない情報 (プライバシー / コスト配慮)

- **ユーザー入力の生文字列**: ハッシュ (`initial_query_hash`) のみ
- **Claude への raw prompt 全文**: 送らない (LLM トレース側で Phoenix を使う想定、§計装図 参照)
- **API キー / OAuth トークン**: 送らない

### イベント間の突合キー

ユーザー別の集計は `user_id`、同一リクエスト内の突合は `session_id` で行う。
すべてのイベントには同一リクエスト由来であることを示す `session_id` (例: `analysis_aa782b9ac2da41e8`) が入ります。OTLP endpoint を設定して Phoenix / Langfuse を立てた場合は `trace_id` も入り、LLM トレース側との突合も可能になります。

### 動作モード切替

| `ANALYTICS_ENABLED` | 挙動 |
|---|---|
| `true` (既定) | `RotatingFileSink` で JSONL を書き出す |
| `false` | `NoOpSink` に置換、JSONL は一切書かれない (テスト用 / 緊急遮断用) |

### ローカル / GCP backend 切替 (Phase 5 Step 10 / PROPOSAL-0010 P5-3)

| `ANALYTICS_STORAGE_BACKEND` | 挙動 |
|---|---|
| `local` (既定) | JSONL は `ANALYTICS_DATA_DIR/raw/` に書かれ、`LocalUploader` が定期的に `uploaded/` へ move (dev 用) |
| `pubsub` (**本番**) | イベント行を `PubSubSink` が直接 Pub/Sub topic (`ANALYTICS_PUBSUB_TOPIC`) に publish → GCS → BQ。8KB 超 payload は `ANALYTICS_GCS_BUCKET` 設定時 GCS に直接書く |
| `gcs` | JSONL は local FS にバッファ後、`LocalUploader` が `GCSTransport` で upload (案B 互換。本 agent では未使用) |

本番 (Cloud Run) の env は `stock-analysis-agent/terraform/` が配線済み
(`ANALYTICS_STORAGE_BACKEND=pubsub` / `ANALYTICS_PUBSUB_TOPIC` /
`ANALYTICS_GCP_PROJECT` / `ANALYTICS_GCS_BUCKET`)。前提となる cross-module 設定は
analytics-platform terraform 側:

- `publisher_service_account_emails` に stock SA → events topic への publish 許可
- `payload_writer_service_account_emails` に stock SA → payloads bucket への書込許可

#### 動作確認 (本番)

```sql
-- 日次の分析回数と Claude コスト (business_event.attributes は JSON 型)
SELECT DATE(event_timestamp) AS day,
       COUNT(*) AS analyses,
       ROUND(SUM(FLOAT64(attributes.total_cost_usd)), 4) AS cost_usd
FROM `analytics_raw.agent_events_external`
WHERE service_name = 'stock-analysis-agent' AND action = 'claude_query_completed'
GROUP BY day ORDER BY day;
```

GCS 直接確認: `gs://sakamomo-family-agent-analytics-raw/events/*.json` (イベント) /
`gs://sakamomo-family-agent-analytics-payloads/payloads/...` (8KB 超の本文)。

### 実機検証スクリプト

```bash
# 実 Claude Agent SDK + 実 yfinance を呼んで JSONL が書かれるか検証
uv run python scripts/integration_check_observability.py
# → data/_integration_check/raw/ 配下に event_type 別 JSONL が生成され、
#    末尾に件数サマリ + PASS/FAIL を表示
```

実行例 (Apple 1 件、約 215 秒、本物の Claude 呼出):
```
event_type counts:
  business_event          : 3
  conversation_event      : 2
  llm_call                : 32
  message                 : 6
  tool_invocation         : 19
PASS: 基本イベント (conversation_event / business_event) を確認
```

---

## セットアップ

### 前提条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker & Docker Compose（Docker 起動の場合）

### ローカル直接起動

```bash
cd stock-analysis-agent

# .env を作成
cp .env.example .env
# CLAUDE_CODE_OAUTH_TOKEN を編集

# 依存パッケージインストール & 起動
make run
```

API: http://localhost:8001

### Docker Compose 起動

```bash
cd stock-analysis-agent
cp .env.example .env
# .env を編集

make dev
```

### テスト実行

```bash
make test
```

---

## ローカル本番 (Mac mini 常駐) — PROPOSAL-0013

GCP と同じ Dockerfile のイメージを Mac mini 上の Docker Compose で動かす。DB は SQLite、
非同期処理は in-process、チャート / 全文はインメモリ配信、LINE Webhook は Tailscale Funnel で
`/api/line` 配下だけを公開する。GCP との違いはすべて環境変数 (`config/local.env`) で切り替える。

- 設計: [docs/PROPOSALS/0013-stock-local-hosting-reversible.md](../docs/PROPOSALS/0013-stock-local-hosting-reversible.md)

```bash
cd stock-analysis-agent
cp config/local.env.example config/local.env && chmod 600 config/local.env    # 秘密情報と PUBLIC_BASE_URL を埋める
cp config/tailscale.env.example config/tailscale.env && chmod 600 config/tailscale.env  # TS_AUTHKEY (初回のみ使用)
make local-config        # compose の設定を検証
make local-up            # backend + Funnel で起動 (Funnel なしは make local-up-private)
make local-logs
```

| 項目 | 場所 |
|---|---|
| 永続データ (SQLite / EDINET cache / 利用ログ) | ホストの `${STOCK_LOCAL_DATA_DIR:-./data/local}` (コンテナ内 `/app/var`) |
| Edinetcode.csv | `${STOCK_LOCAL_DATA_DIR}/edinet-code/Edinetcode.csv` に手動で置く |
| 手元からの確認 | `http://127.0.0.1:${STOCK_LOCAL_PORT:-8001}/health` (localhost のみに公開) |
| 外部公開 | `https://<TS_HOSTNAME>.<tailnet>.ts.net/api/line/*` のみ ([config/tailscale-serve.json](config/tailscale-serve.json)) |

Tailscale 側の事前準備 (HTTPS 証明書・Funnel の許可・auth key) は `config/tailscale.env.example` を参照。
backend は `mem_limit: 4g` / `cpus: 4` で動かす (security-platform と同居するため)。

### 定期処理・死活監視・backup

SQLite に書くのは backend の 1 プロセスだけにするため、日次ジョブは backend 内で動く
(`app/services/scheduler.py`)。どれも既定は無効で、`config/local.env` で個別に止められる。

| ジョブ | 設定 | 内容 |
|---|---|---|
| `edinet_index` | `EDINET_SCHEDULE_ENABLED` / `EDINET_SCHEDULE_TIME` (02:00) | EDINET 書類一覧の rolling 更新 (失敗時は 1 時間後に再試行) |
| `backup` | `BACKUP_ENABLED` / `BACKUP_TIME` (03:00) / `BACKUP_RETENTION_DAYS` | SQLite のオンライン backup を `/app/var/backups` に世代保存 |
| `health` | `HEALTH_CHECK_ENABLED` / `HEALTH_CHECK_INTERVAL_SECONDS` (300) | EDINET・backup の鮮度、Funnel 経由の到達性、分析の連続失敗を確認し、状態が変わったら `HEALTH_NOTIFY_USER_IDS` に LINE |

- 止まっている間に過ぎた日次ジョブは、起動後すぐ 1 回実行する (`/app/var/scheduler_state.json`)
- `HEALTHCHECK_PING_BASE` (security-platform と同じ Ping key) を設定すると、`stock-backend` (生存)・
  `stock-health`・`stock-edinet_index`・`stock-backup`・`stock-offsite_backup` に ping する
- in-process 実行の同時分析数は `ANALYSIS_MAX_CONCURRENCY` (既定 2)。超えた分は「順番待ち」と返して待たせる

```bash
make local-backup                                 # 今すぐ backup
make local-edinet-index ARGS="--from 2026-06-01"  # EDINET index の backfill
OFFSITE_BACKUP_DIR=/Volumes/Backup/stock-analysis make local-offsite-install  # 外部ディスクへ毎日 04:00 にコピー
make local-down && make local-restore && make local-up  # 最新の backup から戻す (BACKUP=... で指定)
```

### ローカル ⇄ GCP の切替

GCP は standby (webhook 非公開・Scheduler 停止、`terraform/README.md` 参照) で残しておき、
どちら向きにも 1 コマンドで切り替える。途中で確認を挟み、失敗したらそこで止まる。
`DRY_RUN=1` で実行するコマンドを表示するだけにできる。

```bash
DRY_RUN=1 make cutover-to-local   # 手順の確認
make cutover-to-local             # GCP → ローカル
make cutover-to-gcp               # ローカル → GCP
```

| 手順 | cutover-to-local | cutover-to-gcp |
|---|---|---|
| 1 | LINE の Webhook 再送を有効にする (手動) | 同じ |
| 2 | ローカル起動 → Funnel 経由で届くか確認 → backend を止める | 最終 backup → backend を止める |
| 3 | GCP の webhook を非公開 → Cloud Tasks の残りを消化 → queue 停止 | 今のコードで build し、webhook / worker / EDINET Job を更新 |
| 4 | Cloud SQL → SQLite へコピーと照合 (`ops.db_copy`) | Secret Manager へ差分を反映 (`ops.secrets_sync`) |
| 5 | EDINET を GCS からローカルへ | standby 解除・queue 再開 |
| 6 | backend 起動 | SQLite → Cloud SQL へコピーと照合 (連番補正) |
| 7 | Webhook をローカルへ切替・疎通テスト (`ops.line_webhook`) | EDINET をローカルから GCS へ |
| 8 | GCP を standby に (`terraform apply -var standby=true`) | Webhook を Cloud Run へ切替・疎通テスト → ローカルを止める |

前提: `gcloud auth login` / `gcloud auth application-default login`、`brew install cloud-sql-proxy`、
`terraform/terraform.tfvars`。`make secrets-diff` / `make webhook-get` で状態を確認できる。

---

## GCP デプロイ (LINE 経由で利用) — PROPOSAL-0011 P1

LINE から `分析 トヨタ` のように使える本番サービスを Cloud Run に配備する。MVP は
**ephemeral SQLite**（永続化は Phase 2）、LLM は Anthropic OAuth token 経由の
claude-agent-sdk（Vertex 不要）。配信は **要約 Flex / チャート画像 / 全文 Markdown
(`.md` DL リンク)** の 3 点セット。

- 設計: [docs/PROPOSALS/0011-stock-analysis-agent-line-gcp.md](../docs/PROPOSALS/0011-stock-analysis-agent-line-gcp.md)
- 手順書: [terraform/README.md](terraform/README.md)（基盤 apply → Secret 投入 →
  Cloud Build → service 化 → PUBLIC_BASE_URL 反映 → Webhook 登録 → 疎通）

必要な Secret（すべて手動投入）: LINE channel secret / access token /
`CLAUDE_CODE_OAUTH_TOKEN` / `BRAVE_API_KEY`。本番は `family_user_ids`（allow-list）と
`analyze_rate_limit_per_day` で Opus コストを抑制する。

```bash
# image build (リポジトリルートから)
gcloud builds submit --config=stock-analysis-agent/cloudbuild.yaml \
  --ignore-file=stock-analysis-agent/cloudbuild.gcloudignore \
  --substitutions=_SHA=$(git rev-parse --short=7 HEAD) .
```

---

## 使用例

### 分析実行（curl）

```bash
# トヨタの株価分析
curl -X POST http://localhost:8001/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"query": "トヨタ", "analysis_types": ["technical", "fundamental"], "period": "3mo"}' \
  --no-buffer

# Apple の株価分析
curl -X POST http://localhost:8001/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"query": "AAPL", "analysis_types": ["technical", "fundamental", "sentiment"]}' \
  --no-buffer
```

### ティッカー解決

```bash
curl -X POST http://localhost:8001/api/resolve-ticker \
  -H "Content-Type: application/json" \
  -d '{"query": "エヌビディア"}'
```

### レポート取得

```bash
curl http://localhost:8001/api/reports/7203.T
```

### 投資信託レコメンド

```bash
# 米国インデックス ETF を 1年トレンドでランキング
curl -X POST http://localhost:8001/api/funds/recommend \
  -H "Content-Type: application/json" \
  -d '{"category": "us_index", "horizon": "1y", "top_n": 5}'

# 全カテゴリ + ゴールデンクロス継続中のみ
curl -X POST http://localhost:8001/api/funds/recommend \
  -H "Content-Type: application/json" \
  -d '{"category": "all", "horizon": "1y", "top_n": 10, "require_uptrend": true}'
```

---

## LLM 設定

- **モデル**: `claude-opus-4-6`（Claude Opus via VertexAI）
- **MCP ツール**: `mcp__brave-search__*`（ニュース検索・センチメント分析）
- **出力**: 日本語分析レポート（SSE ストリーミング）

セキュリティプラットフォームの MCP プロキシ経由で通信する場合は `MCP_PROXY_URL` を設定してください。

---

## ロードマップ

### Phase A — 投資信託レコメンド ✅

- ✅ ETF プロキシによる投資信託ランキング (`POST /api/funds/recommend`)
- ✅ カテゴリ別 (us_index / global / dividend / sector) スコアリング
- ✅ 価格時系列ベースの根拠生成 (リターン / σ / DD / SMA / Sharpe-like)
- ✅ analytics-platform への `business_event(action=funds_recommended)` 連携

### Phase B — LINE Bot 連携 ✅ (本 PR)

- ✅ `POST /api/line/webhook` 受信 + 署名検証 (line-bot-sdk v3)
- ✅ メッセージ → コマンド解釈 (`分析 X` / `おすすめ` / `スクリーニング JP` / `ヘルプ`)
- ✅ 非同期処理 (Webhook 5秒制限対策): 分析コマンドは即 ack → BackgroundTasks で実行 → Push API で結果送信
- ✅ Flex Message でランキング / 分析サマリ表示 (失敗時は text にフォールバック)
- ✅ analytics-platform への `business_event(action=line_webhook_processed)` 連携
- **ステートレス前提** (ユーザー履歴は持たない)

### Phase C — 履歴ベースのパーソナルレコメンド (将来)

- [ ] ユーザー (LINE userId) と問合せ・レポート履歴の紐付け
- [ ] お気に入り銘柄 / ウォッチリストの保存
- [ ] 履歴と既保有 (申告) を踏まえた銘柄レコメンド (相関の低い銘柄を提案 等)
- [ ] 価格アラート / 定期レポート Push 配信
- [ ] DB スキーマ拡張: `line_user_links`, `user_watchlist`, `user_holdings`

> **メモ**: Phase C はユーザー識別が前提のため、Phase B で集める LINE userId をベースに発展させる想定。アラート機能は既存の `alerts` テーブル (現在未使用) を再活用する。

---

## LINE Bot 連携 (Phase B)

### セットアップ

1. [LINE Developers Console](https://developers.line.biz/) で Messaging API チャネルを作成
2. **チャネル基本設定** から `Channel secret`、**Messaging API 設定** から `Channel access token` を取得
3. `.env` に設定:
   ```
   LINE_CHANNEL_SECRET=...
   LINE_CHANNEL_ACCESS_TOKEN=...
   ```
4. アプリを起動し、公開 URL (ngrok / Cloud Run / 自前 HTTPS など) を取得
5. LINE 側の Webhook URL に `https://<your-host>/api/line/webhook` を登録 → Verify
6. Bot を友達追加して動作確認

> 認証情報が未設定の場合 `/api/line/webhook` は 503 を返します。

### サポートコマンド

| 入力例 | 動作 | 応答形式 |
|---|---|---|
| `ヘルプ` / `help` / `?` | コマンド一覧表示 | text |
| `おすすめ` | 全カテゴリの投資信託 Top5 | Flex carousel |
| `おすすめ 米国` | S&P500 / VTI / QQQ 等 | Flex carousel |
| `おすすめ 世界` | VT / ACWI / VEA 等 | Flex carousel |
| `おすすめ 配当` | SCHD / VYM 等 | Flex carousel |
| `おすすめ セクター` | XLK / SOXX / XLF 等 | Flex carousel |
| `スクリーニング` | 日本株の短期上昇候補 Top10 | Flex carousel |
| `スクリーニング JP` / `US` / `ALL` | 市場別スクリーニング | Flex carousel |
| `分析 トヨタ` / `分析 AAPL` | 個別株分析 (Claude Opus) | ack text + Flex bubble (Push) |

各 Flex bubble の「詳細分析」ボタンを押すと自動で `分析 <ticker>` が送信され、深堀分析がスタートします。

### 非同期分析の仕組み

`分析 X` コマンドは Claude Agent SDK を使うため数十秒〜数分かかります。LINE Webhook の 5秒制限を超えないよう以下の流れで処理します:

1. Webhook 受信 → 署名検証 → イベントパース
2. ハンドラが「分析を開始しました…」テキストを **Reply API** で即返信
3. 同時に FastAPI `BackgroundTasks` に分析ジョブを積む
4. Webhook は `200` を返してリクエスト完了
5. バックグラウンドジョブが `run_analysis()` を実行 (orchestrator)
6. 完了後、**Push API** でユーザーに分析サマリ (Flex bubble) を送信

> Push メッセージは LINE 公式アカウントの月間メッセージ数として課金対象になります。スクリーニング・おすすめは秒単位で完了するため Reply API で同期返信します。

### ステートレス設計

Phase B では LINE userId を保存しません。すべてのコマンドは「その場限り」で処理されます。履歴 / お気に入り / 定期通知は Phase C で対応予定です。
