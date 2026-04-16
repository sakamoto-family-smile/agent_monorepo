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
| `ANTHROPIC_API_KEY` | ✅ | Anthropic API キー |
| `BRAVE_API_KEY` | - | センチメント分析用（省略可） |
| `GOOGLE_CLOUD_PROJECT` | - | VertexAI 用 GCP プロジェクト ID |
| `VERTEX_AI_LOCATION` | - | VertexAI リージョン（デフォルト: us-east5） |
| `MCP_PROXY_URL` | - | セキュリティプラットフォーム MCP プロキシ URL |
| `APP_ENV` | - | 実行環境（デフォルト: local） |
| `DB_PATH` | - | SQLite DB パス（デフォルト: data/stock_analysis.db） |

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
# ANTHROPIC_API_KEY を編集

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
