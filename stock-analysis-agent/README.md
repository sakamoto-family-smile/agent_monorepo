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

**POST /api/analyze リクエスト**:

```json
{
  "query": "トヨタ",
  "analysis_types": ["technical", "fundamental", "sentiment"],
  "period": "3mo"
}
```

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

---

## 分析基盤 (analytics-platform) への送信情報

このエージェントは [`../analytics-platform`](../analytics-platform/) に対して、リクエスト 1 本ごとに以下のイベントを業務ログ JSONL として書き出します。`ANALYTICS_DATA_DIR/raw/service_name=stock-analysis-agent/event_type=*/dt=YYYY-MM-DD/hour=HH/*.jsonl` に Hive パーティション形式で蓄積されます。

### 送信されるイベント種別と発火タイミング

| event_type | 発火タイミング | 1 リクエストあたりの典型件数 |
|---|---|---|
| `conversation_event` | リクエスト開始時 (`started`)、正常終了時 (`ended`)、例外時 (`aborted`) | 2 |
| `business_event` (action=`ticker_resolved`) | ticker 解決完了時 | 1 |
| `business_event` (action=`claude_query_completed`) | Claude Agent SDK の `ResultMessage` 受信時 | 1 |
| `business_event` (action=`report_saved`) | 分析レポート DB 保存完了時 | 1 |
| `llm_call` | Claude SDK の `AssistantMessage` 受信ごと | 数十 (turn 数依存) |
| `tool_invocation` | MCP ツール (`brave-search` 等) の結果受信ごと | 0〜数十 |
| `message` | アシスタントの本文 `TextBlock` ごと | 数件 |
| `error_event` | orchestrator 内で例外発生時 | 0 or 1 |

### 各イベントに含まれる主要フィールド

すべて [`analytics_platform.observability.schemas`](../analytics-platform/analytics_platform/observability/schemas.py) で Pydantic 検証されます。共通フィールド (`event_id` / `event_timestamp` / `service_name` / `service_version` / `environment` / `trace_id` / `span_id` / `session_id` / `severity`) に加え、種別ごとに以下が付与されます。

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
- `content_text` (8KB 以下) **または** `content_uri` (8KB 超は `data/analytics/payloads/.../*.txt` に退避し `file://` URI を入れる)
- `content_hash` (`sha256:<hex>`)
- `content_preview` (先頭 500 文字)
- `content_size_bytes` / `content_truncated`

#### `business_event` — ドメインアクション
- `business_domain` = `"stock_analysis"`
- `action` = `ticker_resolved` / `claude_query_completed` / `report_saved`
- `resource_type` / `resource_id`
- `attributes` (アクション固有の付帯情報、例: `ticker_resolved` には `company_name` / `confidence` / `source`)

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

すべてのイベントには同一リクエスト由来であることを示す `session_id` (例: `analysis_aa782b9ac2da41e8`) が入ります。OTLP endpoint を設定して Phoenix / Langfuse を立てた場合は `trace_id` も入り、LLM トレース側との突合も可能になります。

### 動作モード切替

| `ANALYTICS_ENABLED` | 挙動 |
|---|---|
| `true` (既定) | `RotatingFileSink` で JSONL を書き出す |
| `false` | `NoOpSink` に置換、JSONL は一切書かれない (テスト用 / 緊急遮断用) |

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

---

## LLM 設定

- **モデル**: `claude-opus-4-6`（Claude Opus via VertexAI）
- **MCP ツール**: `mcp__brave-search__*`（ニュース検索・センチメント分析）
- **出力**: 日本語分析レポート（SSE ストリーミング）

セキュリティプラットフォームの MCP プロキシ経由で通信する場合は `MCP_PROXY_URL` を設定してください。
