# analytics-platform

エージェントシステム (Claude Agent SDK / MCP / FastAPI 等) から発生する
**チャット履歴・トレース・メトリクス・業務イベント**を収集する分析基盤。
本 PR では **ローカル (Phoenix + OTel + JSONL + DuckDB + dbt) のみ** を実装。
GCP (Langfuse / BigQuery / GCS) は後続 PR で対応予定。

---

## 0. Quickstart

### 0.1 前提ツール

| ツール | バージョン | 備考 |
|---|---|---|
| Python | 3.12+ | `pyproject.toml` で指定 |
| uv | 最新 | パッケージ管理 |
| Docker / Docker Compose | 任意 | Phoenix を立てる場合のみ必要 |

### 0.2 セットアップ

```bash
cd agent_monorepo/analytics-platform

# 1. 環境変数テンプレートをコピー
cp .env.example .env

# 2. 依存インストール
make install
```

### 0.3 Phoenix 起動 (任意)

```bash
# 別ターミナルで起動
make phoenix-up
# → http://localhost:6006

# 止めるとき
make phoenix-down
```

Phoenix を起動していなくても、OTel Exporter はバッファしつつ失敗ログを出すだけでアプリは動作する (JSONL 出力のみ確認したい場合はスキップしてよい)。

### 0.4 デモを走らせる

```bash
# 業務ログ (JSONL) を生成 → dbt で DuckDB に取り込む
make etl

# DuckDB を直接開いて確認
uv run python -c "import duckdb; print(duckdb.connect('data/analytics.duckdb').sql('SELECT event_type, COUNT(*) FROM stg_agent_events GROUP BY 1').df())"
```

### 0.5 テスト

```bash
make test          # pytest
make lint          # ruff check
make check         # lint + test
```

---

## 1. アーキテクチャ (ローカル範囲)

```
[アプリ (demo_emit / future: agents)]
   │  OpenTelemetry SDK                 AnalyticsLogger
   │  (LLM / HTTP / custom spans)       (Pydantic 検証 → バッファ → 非同期フラッシュ)
   ▼                                   ▼
 Phoenix                            ./data/raw/service_name=.../event_type=.../dt=.../hour=.../*.jsonl
 (Docker)                                │
   │                                     │  LocalUploader (raw → uploaded, 失敗は dead_letter)
   │                                     ▼
   │                                  ./data/uploaded/...
   │                                     │  dbt-duckdb
   │                                     ▼
   │                                  ./data/analytics.duckdb (raw → staging → marts)
   │                                     │
   └── 突合キー (trace_id) で join       ▼
                                     Metabase / DuckDB CLI 等
```

- **計装コードは 1 回だけ書けばよい**: OTel Exporter のエンドポイントだけ `.env` で切り替わる
- **業務ログ は常に 100% 書かれる**: OTel 側をサンプリングしても `trace_id` 突合は機能する (設計書 §7.5.2)
- **コンテンツの振り分け**: `content_inline_threshold_bytes` (既定 8KB) 以下なら `content_text` に直埋、超過なら `./data/payloads/` へ退避し `content_uri` に `file://...` を入れる

---

## 2. コンポーネント構成

分析基盤は **6 レイヤー** で構成され、各レイヤーは次のレイヤーにしか依存しない (上→下の一方向)。レイヤー間の境界は Protocol / dataclass で抽象化されており、GCP 版への差替ポイントもここ。

### 2.1 レイヤー全体像

```
┌──────────────────────────────────────────────────────────────────┐
│ L1. Producer (計装される側)                                      │
│    エージェント / demo_emit.py / 将来の FastAPI 等               │
└────────────┬──────────────────────────┬──────────────────────────┘
             │ OTel SDK                 │ AnalyticsLogger.emit()
             │ (LLM / HTTP / custom)    │ (validate → 内製 JSONL)
             ▼                          ▼
┌──────────────────────────────────────────────────────────────────┐
│ L2. Instrumentation (app/observability/)                         │
│    tracer.py / context.py / logger.py / schemas.py               │
│    analytics_logger.py / content.py / hashing.py                 │
└────────────┬──────────────────────────┬──────────────────────────┘
             │ OTLP/HTTP                │ JSONL バッチ
             ▼                          ▼
┌──────────────────┐       ┌──────────────────────────────────────┐
│ L3a. Trace Sink  │       │ L3b. File Sink (app/observability/   │
│   Phoenix        │       │             sinks/file_sink.py)      │
│   (Docker)       │       │ Hive パーティションで JSONL を追記    │
│   :6006          │       │   data/raw/service_name=.../...      │
└──────────────────┘       └─────────────┬────────────────────────┘
                                         │ raw → uploaded
                                         │ (失敗時 dead_letter)
                                         ▼
┌──────────────────────────────────────────────────────────────────┐
│ L4. Uploader (app/uploader/local_uploader.py)                    │
│    Protocol = UploadTransport。ローカルは LocalMoveTransport       │
│    (単なる os.rename)。GCP 版は GCSTransport に差替可能            │
└────────────────────────┬─────────────────────────────────────────┘
                         │ data/uploaded/...
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│ L5. Transform (dbt/models/)                                      │
│    dbt-duckdb (ローカル) / dbt-bigquery (将来)                      │
│    raw → staging → marts の 3 層                                  │
│    成果物: data/analytics.duckdb                                   │
└────────────────────────┬─────────────────────────────────────────┘
                         │ SQL / DataFrame
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│ L6. Query / Visualization                                        │
│    DuckDB CLI / Python client / Metabase (将来) / Phoenix UI      │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 コンポーネント一覧 (1 レイヤー = 複数モジュール)

| # | コンポーネント | 役割 | 主要モジュール | 技術 | 差替点 (GCP 版) |
|---|---|---|---|---|---|
| L1 | Producer | 業務アクション / LLM 呼出で span + event を発行 | `scripts/demo_emit.py`, 将来: 各エージェント | OTel SDK + AnalyticsLogger | 変更なし |
| L2-a | Tracer 初期化 | プロセス起動時に 1 度だけ OTLP exporter を設定 | `app/observability/tracer.py` | `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-http` | endpoint / headers / sampler を env で差替 |
| L2-b | Trace Context | 現行 span から `trace_id` / `span_id` を W3C hex で取出 | `app/observability/context.py` | OTel API | 変更なし |
| L2-c | Structlog | 構造化ログに `trace_id` を自動注入 | `app/observability/logger.py` | `structlog` | 変更なし |
| L2-d | Event Schema | 7 種の `event_type` を Pydantic Discriminated Union で型安全化 | `app/observability/schemas.py` | `pydantic` v2 | 変更なし |
| L2-e | Hashing | `sha256:<hex>` を強制 | `app/observability/hashing.py` | stdlib hashlib | 変更なし |
| L2-f | Content Router | 大きなコンテンツを inline / URI 参照に振り分け | `app/observability/content.py` | `PayloadWriter` Protocol | `LocalFilePayloadWriter` → `GCSPayloadWriter` |
| L2-g | AnalyticsLogger | validate → リングバッファ → 非同期フラッシュ | `app/observability/analytics_logger.py` | `pydantic` + `uuid_utils` | 変更なし |
| L3-a | Trace Sink | OTLP span を表示・保存 | (外部: Phoenix) | `arizephoenix/phoenix` Docker | Langfuse on GKE |
| L3-b | File Sink | JSONL を Hive パーティションに書き出し | `app/observability/sinks/file_sink.py` | stdlib asyncio + gzip | 同じ構造で GCS に直書きする sink を追加可能 |
| L4 | Uploader | `raw/` → `uploaded/` を移動、失敗時 `dead_letter/` | `app/uploader/local_uploader.py` | `tenacity` (指数バックオフ) + `UploadTransport` Protocol | `LocalMoveTransport` → `GCSTransport` |
| L5-a | Raw 層 | JSONL を DuckDB table として物理化 | `dbt/models/raw/raw_agent_events.sql` | `dbt-duckdb` + `read_json_auto` | `dbt-bigquery` + external table |
| L5-b | Staging 層 | 共通フィールド正規化 + `ingested_at` 付与 + TIMESTAMPTZ 化 | `dbt/models/staging/*.sql` | dbt core | 共通 (adapter だけ切替) |
| L5-c | Marts 層 | KPI テーブル (`daily_agent_metrics` / `cache_efficiency` / `delivery_health`) | `dbt/models/marts/*.sql` | dbt core | 共通 |
| L6-a | Query | SQL で直接参照 | DuckDB CLI / Python `duckdb` | DuckDB file | BigQuery クライアント |
| L6-b | Viz | ダッシュボード (Phase 7 予定) | 未実装 | Metabase / Looker Studio | 同じ |
| X | CI | PR で pytest + demo + dbt 一気通貫 | `.github/workflows/pr-tests.yml` の `test-analytics-platform` | GitHub Actions + `uv` | 共通 |
| X | Security Scan | bandit / gitleaks | `security-platform/config/scan.yaml` の `source_directories` | 共通 | 共通 |

### 2.3 依存関係と差替境界

GCP 版に拡張する際は、**L2-f / L3-b / L4 / L5 の 4 箇所**だけ差し替えれば上位のアプリコードは無変更:

```
L1 (アプリ)         — 変更なし
L2 (observability) — 変更なし (env で endpoint 切替のみ)
      ├─ L2-f: PayloadWriter       ← GCSPayloadWriter 実装を注入
      │
L3    ├─ L3-a: Phoenix             ← Langfuse on GKE を立て、URL を env で指す
      └─ L3-b: RotatingFileSink    ← GCS 直書き sink を追加 (or L4 経由で吸収)
      │
L4    └─ UploadTransport            ← GCSTransport を実装
      │
L5      dbt-duckdb                 ← dbt-bigquery profile 追加、SQL はほぼ共通
```

差替インターフェース (Protocol):

- `observability/content.py:PayloadWriter.write(service_name, event_id, content, extension) -> str`
- `observability/sinks/file_sink.py:JsonlSink.write_batch(lines: list[str]) -> None`
- `uploader/local_uploader.py:UploadTransport.send(src, *, dest_root) -> Path`

### 2.4 データフロー (1 リクエスト分)

1. アプリが `tracer.start_as_current_span("llm.call")` で span 開始 → **L3-a Phoenix** へ OTLP 送信
2. 同じ span 内で `analytics_logger.emit(event_type="llm_call", ...)` を呼ぶ → Pydantic 検証 → L2-g のリングバッファに append
3. 大きいコンテンツは **L2-f ContentRouter** が `data/payloads/...` に書き、`content_uri = file://...` を event に詰める
4. 背景フラッシュ (もしくは明示 `flush()`) が **L3-b RotatingFileSink** を呼び、`data/raw/service_name=.../event_type=.../dt=.../hour=.../*.jsonl` に追記
5. **L4 LocalUploader** が定期的に `raw/` → `uploaded/` を移動 (今は手動、将来 cron / systemd)
6. **L5 dbt** が `data/uploaded/**/*.jsonl` を `read_json_auto(hive_partitioning=true)` で読み、raw → staging → marts をリビルド
7. 分析は **L6 DuckDB** で SQL、トレース UI は **L3-a Phoenix** を見る。`trace_id` で両者を突合

### 2.5 開発フロー上のコンポーネント

| フェーズ | 触るもの |
|---|---|
| 新しい event_type を追加 | `observability/schemas.py` に `SomethingEvent` を足し `AnyEvent` に入れる + `dbt/models/staging/stg_something.sql` 追加 |
| 新しい KPI を追加 | `dbt/models/marts/mart_*.sql` 追加 + `marts/schema.yml` にテスト追加 |
| GCP へ移行 | §2.3 の 4 箇所のみ差替 |
| 既存エージェント計装 | producer 側 (`L1`) で `setup_tracer()` + `AnalyticsLogger` を DI するだけ |

---

## 3. コード構成

```
analytics-platform/
├── app/
│   ├── config.py                # pydantic-settings で .env を読む
│   └── observability/
│       ├── schemas.py           # Pydantic discriminated union (event_type 7 種)
│       ├── hashing.py           # sha256:<hex> 強制
│       ├── context.py           # OTel Context → trace_id / span_id (W3C 形式)
│       ├── tracer.py            # TracerProvider 初期化 (Phoenix / Langfuse)
│       ├── logger.py            # structlog 設定 (trace_id 自動注入)
│       ├── content.py           # ContentRouter (inline / URI 振り分け)
│       ├── analytics_logger.py  # AnalyticsLogger 本体 (バッファ + flush)
│       └── sinks/
│           └── file_sink.py     # Hive パーティション JSONL シンク
│   └── uploader/
│       └── local_uploader.py    # raw → uploaded (失敗は dead_letter)
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml
│   ├── models/
│   │   ├── raw/raw_agent_events.sql         # read_json_auto + hive_partitioning
│   │   ├── staging/stg_agent_events.sql     # 共通フィールド + ingested_at
│   │   ├── staging/stg_llm_calls.sql
│   │   ├── staging/stg_messages.sql
│   │   ├── staging/stg_tool_invocations.sql
│   │   ├── marts/mart_daily_agent_metrics.sql
│   │   ├── marts/mart_cache_efficiency.sql
│   │   └── marts/mart_delivery_health.sql
│   └── tests/assert_cache_hit_ratio_bounds.sql
├── scripts/
│   ├── demo_emit.py             # 20 セッション分のサンプルトレース生成
│   └── run_etl.sh               # demo → dbt run → dbt test
├── tests/                       # pytest
├── data/                        # 実行時に生成 (.gitignored)
├── docker-compose.yml           # Phoenix
├── Makefile
├── pyproject.toml
└── .env.example
```

---

## 4. 主要な設計判断

設計書 (セッション冒頭に貼付) を参照。本 PR で特に重視した点:

- **Discriminated Union**: `event_type` ごとの必須フィールドを Pydantic が emit 時点で強制
- **Hive パーティション**: `service_name=.../event_type=.../dt=.../hour=.../` を `RotatingFileSink` がそのまま掘る。DuckDB `read_json_auto(..., hive_partitioning=true)` が即読める
- **`sha256:<hex>` prefix 強制**: `content_hash` / `input_args_hash` 等は `sha256_prefixed()` で必ず整形
- **`ingested_at` は dbt Staging 層で付与**: アプリ側では発行しない (設計書 §6.2 注記)
- **ローカル擬似 GCS**: `data/raw/ → uploaded/ → dead_letter/` の 3 段構成で、将来 GCS Uploader に差し替え可能
- **大きなコンテンツ**: 8KB (既定) 超は `data/payloads/{service}/{dt}/{event_id}.{ext}` に退避し `file://...` URI を付与

---

## 5. 主要 API

### 5.1 AnalyticsLogger

```python
from observability.analytics_logger import AnalyticsLogger
from observability.sinks.file_sink import RotatingFileSink

sink = RotatingFileSink(root_dir="./data/raw", service_name="my-agent")
logger = AnalyticsLogger(
    service_name="my-agent",
    service_version="0.1.0",
    environment="local",
    sink=sink,
)

event_id = logger.emit(
    event_type="llm_call",
    event_version="1.0.0",
    severity="INFO",
    fields={
        "llm_provider": "anthropic",
        "llm_model": "claude-opus-4-7",
        "input_tokens": 1500,
        "output_tokens": 300,
    },
    user_id="u_abc",
    session_id="conv_xyz",
)
await logger.flush()
```

`trace_id` / `span_id` は OTel Context から自動取得される (スパンが無ければ None)。

### 5.2 ContentRouter

```python
from observability.content import ContentRouter, LocalFilePayloadWriter

router = ContentRouter(
    writer=LocalFilePayloadWriter(root_dir="./data/payloads"),
    inline_threshold_bytes=8192,
)
stored = router.route(
    service_name="my-agent",
    event_id="msg_01",
    content="...",
    mime_type="text/markdown",
)
logger.emit(
    event_type="message",
    event_version="1.0.0",
    severity="INFO",
    fields={"message_id": "msg_01", "message_role": "user", "message_index": 0, **stored.to_fields()},
)
```

### 5.3 tracer.setup_tracer

```python
from observability.tracer import setup_tracer

tracer = setup_tracer(
    service_name="my-agent",
    service_version="0.1.0",
    environment="local",
    otlp_endpoint="http://localhost:6006/v1/traces",
    sampling_ratio=1.0,
)
with tracer.start_as_current_span("llm.call") as span:
    span.set_attribute("llm.model_name", "claude-opus-4-7")
    ...
```

---

## 6. 既知の未対応 (後続 PR 予定)

- **GCP 版**: Langfuse on GKE / BigQuery / GCS Uploader / Cloud Workflows
- **Enrichment パイプライン**: `content_summary` / `content_keywords` / Vector Search
- **BI ダッシュボード**: Metabase / Looker Studio の dashboard 定義
- **アラート**: Grafana Alert / Cloud Monitoring
- **既存エージェント (`kanie-lab-agent`, `lifeplanner-agent`) への計装**: 別 PR

---

## 7. 環境変数一覧

主要なもの。詳細は `.env.example` 参照。

| 変数 | 既定 | 用途 |
|---|---|---|
| `ENV` | `local` | `local` / `gcp` |
| `SERVICE_NAME` | `analytics-platform-demo` | event.service_name |
| `SERVICE_VERSION` | `0.1.0` | event.service_version |
| `ANALYTICS_DATA_DIR` | `./data` | 各種サブフォルダのルート |
| `ANALYTICS_COMPRESS` | `false` | JSONL を gzip するか |
| `CONTENT_INLINE_THRESHOLD_BYTES` | `8192` | inline / URI 振り分け閾値 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:6006/v1/traces` | Phoenix / Langfuse |
| `OTEL_EXPORTER_OTLP_HEADERS` | - | `k1=v1,k2=v2` 形式 |
| `OTEL_SAMPLING_RATIO` | `1.0` | 0.0〜1.0 |
| `LOG_LEVEL` | `INFO` | structlog レベル |
