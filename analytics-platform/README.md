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

### 0.6 ライブラリとして別エージェントから使う

モノレポ内の他エージェント (例: `stock-analysis-agent` / `lifeplanner-agent`) からは `uv` の path dependency として取り込む:

```toml
# 消費側エージェントの pyproject.toml
[project]
dependencies = [
  ...
  "analytics-platform",
]

[tool.uv.sources]
analytics-platform = { path = "../analytics-platform" }
```

```python
# 消費側コード例
from analytics_platform.observability.tracer import setup_tracer
from analytics_platform.observability.analytics_logger import AnalyticsLogger
from analytics_platform.observability.sinks.file_sink import RotatingFileSink
```

書き出し先 (`ANALYTICS_DATA_DIR` 既定 `./data`) は env で上書き可能。複数エージェントが同じディレクトリに書く運用も、`service_name` が Hive パーティションキーになるため衝突しない。

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
│ L2. Instrumentation (analytics_platform/observability/)                         │
│    tracer.py / context.py / logger.py / schemas.py               │
│    analytics_logger.py / content.py / hashing.py                 │
└────────────┬──────────────────────────┬──────────────────────────┘
             │ OTLP/HTTP                │ JSONL バッチ
             ▼                          ▼
┌──────────────────┐       ┌──────────────────────────────────────┐
│ L3a. Trace Sink  │       │ L3b. File Sink (analytics_platform/observability/   │
│   Phoenix        │       │             sinks/file_sink.py)      │
│   (Docker)       │       │ Hive パーティションで JSONL を追記    │
│   :6006          │       │   data/raw/service_name=.../...      │
└──────────────────┘       └─────────────┬────────────────────────┘
                                         │ raw → uploaded
                                         │ (失敗時 dead_letter)
                                         ▼
┌──────────────────────────────────────────────────────────────────┐
│ L4. Uploader (analytics_platform/uploader/local_uploader.py)                    │
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
| L2-a | Tracer 初期化 | プロセス起動時に 1 度だけ OTLP exporter を設定 | `analytics_platform/observability/tracer.py` | `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-http` | endpoint / headers / sampler を env で差替 |
| L2-b | Trace Context | 現行 span から `trace_id` / `span_id` を W3C hex で取出 | `analytics_platform/observability/context.py` | OTel API | 変更なし |
| L2-c | Structlog | 構造化ログに `trace_id` を自動注入 | `analytics_platform/observability/logger.py` | `structlog` | 変更なし |
| L2-d | Event Schema | 7 種の `event_type` を Pydantic Discriminated Union で型安全化 | `analytics_platform/observability/schemas.py` | `pydantic` v2 | 変更なし |
| L2-e | Hashing | `sha256:<hex>` を強制 | `analytics_platform/observability/hashing.py` | stdlib hashlib | 変更なし |
| L2-f | Content Router | 大きなコンテンツを inline / URI 参照に振り分け | `analytics_platform/observability/content.py` | `PayloadWriter` Protocol | `LocalFilePayloadWriter` → `GCSPayloadWriter` |
| L2-g | AnalyticsLogger | validate → リングバッファ → 非同期フラッシュ | `analytics_platform/observability/analytics_logger.py` | `pydantic` + `uuid_utils` | 変更なし |
| L3-a | Trace Sink | OTLP span を表示・保存 | (外部: Phoenix) | `arizephoenix/phoenix` Docker | Langfuse on GKE |
| L3-b | File Sink | JSONL を Hive パーティションに書き出し | `analytics_platform/observability/sinks/file_sink.py` | stdlib asyncio + gzip | 同じ構造で GCS に直書きする sink を追加可能 |
| L4 | Uploader | `raw/` → `uploaded/` を移動、失敗時 `dead_letter/` | `analytics_platform/uploader/local_uploader.py` | `tenacity` (指数バックオフ) + `UploadTransport` Protocol | `LocalMoveTransport` → `GCSTransport` |
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

- `analytics_platform/observability/content.py:PayloadWriter.write(service_name, event_id, content, extension) -> str`
- `analytics_platform/observability/sinks/file_sink.py:JsonlSink.write_batch(lines: list[str]) -> None`
- `analytics_platform/uploader/local_uploader.py:UploadTransport.send(src, *, dest_root) -> Path`

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
| 新しい event_type を追加 | `analytics_platform/observability/schemas.py` に `SomethingEvent` を足し `AnyEvent` に入れる + `dbt/models/staging/stg_something.sql` 追加 |
| 新しい KPI を追加 | `dbt/models/marts/mart_*.sql` 追加 + `marts/schema.yml` にテスト追加 |
| GCP へ移行 | §2.3 の 4 箇所のみ差替 |
| 既存エージェント計装 | producer 側 (`L1`) で `setup_tracer()` + `AnalyticsLogger` を DI するだけ |

---

## 3. GCP 版インフラ構成 (想定 + 先行実装)

> **ステータス (2026-04)**: Phase 5 のうち以下を実装済:
> - **L2-f GCSPayloadWriter / L4 GCSTransport / env 駆動 factory** (`ANALYTICS_STORAGE_BACKEND=gcs`)
> - **L5 dbt-bigquery 対応** (cross-DB マクロ + BQ external table source + `--target gcp`)
> - **scripts/gcp_bootstrap.sh** で BQ dataset / external table を idempotent に作成
> - **Cloud Run Jobs コンテナ** (`Dockerfile` + `cloudbuild.yaml`、§3.5.1)
>
> 未着手: Cloud Workflows + Scheduler / Cloud Monitoring / Langfuse on GKE / Terraform。方針は設計書 §3 / §4 / §9 / §13 に準拠。

### 3.0 env 駆動の GCS 切替 (実装済)

consumer エージェントが tech-news-agent / piyolog-analytics などで以下の env を設定するだけで、JSONL の Upload と大容量 payload の書き出しが GCS に切り替わる:

| 環境変数 | 既定 | 説明 |
|---|---|---|
| `ANALYTICS_STORAGE_BACKEND` | `local` | `local` \| `gcs`。`gcs` 指定時のみ下記が効く |
| `ANALYTICS_GCS_BUCKET` | — | GCS バケット名 (`gcs` 時必須、未設定なら local にフォールバック + 警告) |
| `ANALYTICS_GCS_RAW_PREFIX` | `uploaded/` | raw JSONL の upload prefix |
| `ANALYTICS_GCS_PAYLOAD_PREFIX` | `payloads/` | 大容量 payload の prefix |
| `ANALYTICS_GCP_PROJECT` | (ADC から自動推論) | GCP プロジェクト ID。Cloud Run + Workload Identity なら省略可 |

使い方 (consumer 側):

```python
from pathlib import Path
from analytics_platform.gcp_config import build_payload_writer, build_upload_transport

# Content router: 大容量 payload の書き出し先を env で切替
writer = build_payload_writer(local_root=Path("./data/payloads"))
router = ContentRouter(writer=writer, inline_threshold_bytes=8192)

# Uploader: JSONL Upload 先を env で切替
transport = build_upload_transport(raw_root=Path("./data/raw"))
uploader = LocalUploader(
    raw_root=Path("./data/raw"),
    uploaded_root=Path("./data/uploaded_noop"),   # GCS 時は未使用
    dead_letter_root=Path("./data/dead_letter"),
    transport=transport,
)
```

インストール: `uv sync --extra gcs` (optional `[gcs]` extra、`google-cloud-storage` を含む)。

### 3.0.1 BigQuery / dbt-bigquery 対応 (実装済)

dbt 側は **cross-DB マクロ** + **adapter dispatch** で `--target local` (DuckDB) / `--target gcp` (BigQuery) を切替可能。SQL ロジックは共通、文法差は `dbt/macros/cross_db.sql` に集約。

#### 必要な env

| 環境変数 | 既定 | 説明 |
|---|---|---|
| `ANALYTICS_BQ_PROJECT` | — | GCP project id (必須) |
| `ANALYTICS_BQ_LOCATION` | `US` | BQ location (`US` / `asia-northeast1` 等) |
| `ANALYTICS_BQ_RAW_DATASET` | `analytics_raw` | raw external table 配置先 |
| `ANALYTICS_BQ_STAGING_DATASET` | `analytics_staging` | staging dataset |
| `ANALYTICS_BQ_MARTS_DATASET` | `analytics_marts` | marts dataset |
| `ANALYTICS_BQ_DEFAULT_DATASET` | `analytics_staging` | profiles.yml の `dataset` (target.schema 用) |
| `ANALYTICS_BQ_RAW_TABLE` | `agent_events_external` | raw external table 名 |

#### セットアップ手順 (初回のみ)

```bash
# 1. dbt-bigquery + google-cloud-bigquery を入れる
make install-gcp

# 2. ADC 認証 (ローカルから動かす場合)
gcloud auth login
gcloud auth application-default login
gcloud config set project "${ANALYTICS_BQ_PROJECT}"

# 3. GCS バケットは既に作成済の前提 (terraform 等)。
#    consumer 側の Uploader が gs://${ANALYTICS_GCS_BUCKET}/uploaded/ 配下に
#    Hive パーティションで JSONL を吐き続ける。

# 4. BQ dataset + external table を作成 (idempotent)
make gcp-bootstrap
# → analytics_raw / analytics_staging / analytics_marts dataset を作成
# → analytics_raw.agent_events_external を gs://...uploaded/ 上に張る
```

#### 実行

```bash
# 接続を伴わないパースだけ (CI で SQL の妥当性チェック用)
make dbt-parse-bq

# 実行 (BigQuery にクエリが走る)
make dbt-run-bq
make dbt-test-bq
```

#### 仕組み

dbt model の文法差は次の 5 個のマクロで吸収:

| マクロ | DuckDB | BigQuery |
|---|---|---|
| `star_except(['a','b'])` | `EXCLUDE (a, b)` | `EXCEPT (a, b)` |
| `quantile_cont(col, p)` | `QUANTILE_CONT(col, p)` (厳密) | `APPROX_QUANTILES(col, 100)[OFFSET(p*100)]` (近似) |
| `epoch_seconds_diff(later, earlier)` | `EXTRACT(EPOCH FROM (later - earlier))` | `TIMESTAMP_DIFF(later, earlier, MILLISECOND) / 1000.0` |
| `parse_event_timestamp(col)` | `(CAST(col AS TIMESTAMP) AT TIME ZONE 'UTC')` | `TIMESTAMP(col)` |
| `date_from_timestamp(col)` | `DATE(col)` | `DATE(col, 'UTC')` |

データ型は dbt 標準の `dbt.type_bigint()` / `dbt.type_float()` / `dbt.type_boolean()` を使用 (DuckDB `BIGINT`/`DOUBLE` ↔ BQ `INT64`/`FLOAT64` を自動展開)。

スキーマ命名は `dbt/macros/generate_schema_name.sql` で:
- DuckDB: `{target.schema}_{custom}` (既定挙動。`main_raw` / `main_staging` / `main_marts`)
- BigQuery: `analytics_{custom}` 固定 (dataset を明示的に分離)

raw 層は adapter で物理化方式が異なる:
- DuckDB: `read_json_auto('../data/raw/**/*.jsonl*', hive_partitioning=true)` を `table` で物理化
- BigQuery: `gcp_bootstrap.sh` で作った external table を `view` で参照 (GCS Hive partitioning は autodetect)

### 3.1 GCP アーキテクチャ全体像

```
┌──────────────────────────────────────────────────────────────────────┐
│ Agent Services (Cloud Run / GKE / GCE 上で稼働)                      │
│   OTel SDK ────────────────────────────┐                             │
│   AnalyticsLogger ──────────┐          │                             │
└─────────────────────────────┼──────────┼─────────────────────────────┘
                              │ JSONL    │ OTLP/HTTPS
                              ▼          ▼
                    ┌────────────────┐  ┌──────────────────────────┐
                    │ Cloud Run      │  │ Langfuse on GKE (self-   │
                    │  Sidecar or    │  │  hosted, Helm chart)     │
                    │  Uploader Job  │  │  - PostgreSQL (Cloud SQL)│
                    │                │  │  - ClickHouse (GKE)      │
                    └────┬───────────┘  │  - Redis (Memorystore)   │
                         │ Resumable    │  - Object store (GCS)    │
                         │ upload       │                          │
                         ▼              │   Auth: Cloud Load        │
                    ┌────────────────┐  │   Balancer + IAP          │
                    │ GCS (raw /     │  └────────┬─────────────────┘
                    │  uploaded /    │           │ Export
                    │  payloads /    │           │ (nightly batch)
                    │  dead_letter)  │           ▼
                    └────┬───────────┘  ┌──────────────────────────┐
                         │              │ BigQuery                 │
                         │ Load Job     │  - raw.langfuse_*        │
                         │ (hourly)     │                          │
                         ▼              │                          │
                    ┌────────────────────────────────────────────┐  │
                    │ BigQuery                                   │  │
                    │  raw.agent_events (external / native)      │◀─┘
                    │  staging.stg_*                             │
                    │  marts.mart_*                              │
                    └────┬───────────────────────────────────────┘
                         │ dbt-bigquery
                         │ (Cloud Run Jobs, Cloud Workflows で起動)
                         ▼
                    ┌────────────────────────────────────────────┐
                    │ Looker Studio / Metabase / BQ Console      │
                    └────────────────────────────────────────────┘

                    Orchestration (右側経路)
                    Cloud Scheduler ──▶ Cloud Workflows ──▶ Cloud Run Jobs
                                                           (Uploader / dbt)

                    Alerting
                    Cloud Monitoring ──▶ Pub/Sub ──▶ Cloud Run (Slack / Email)
                    Grafana on GKE (option) ──▶ Slack
```

### 3.2 ローカル → GCP コンポーネント対応表

| # | ローカル | GCP 版 | 差替ポイント |
|---|---|---|---|
| L1 | `scripts/demo_emit.py` / 将来のエージェント | 同じアプリ (Cloud Run / GKE) | なし (env のみ切替) |
| L2-a | `tracer.py` (Phoenix endpoint) | 同じ (Langfuse OTLP endpoint に切替) | `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_EXPORTER_OTLP_HEADERS` |
| L2-f | `LocalFilePayloadWriter` (`file://`) | `GCSPayloadWriter` (`gs://`) | `PayloadWriter` Protocol 実装 |
| L3-a | Phoenix (Docker) | **Langfuse on GKE** (Helm) + Cloud SQL / ClickHouse / Memorystore Redis / GCS | デプロイ先 |
| L3-b | `RotatingFileSink` (ローカル FS) | 同じ `RotatingFileSink` でローカル Tmp → サイドカーが GCS アップロード | 変更なし (ファイル出力先がサイドカー共有ボリューム) |
| L4 | `LocalMoveTransport` | `GCSTransport` (`google-cloud-storage` の resumable upload) | `UploadTransport` Protocol 実装 |
| L5 | `dbt-duckdb` + `./data/analytics.duckdb` | `dbt-bigquery` + BigQuery dataset | profiles.yml に `gcp` target 追加 |
| L6-a | DuckDB CLI | `bq` CLI / BigQuery Python client | クライアント差替 |
| L6-b | (未実装) | **Looker Studio** (ステークホルダー) / **Metabase on GKE** (社内ダッシュボード) | 新規構築 |
| X-1 | - | **Cloud Scheduler** + **Cloud Workflows** + **Cloud Run Jobs** | オーケストレーション追加 |
| X-2 | - | **Cloud Monitoring** + **Pub/Sub** + **Grafana Alerting** → Slack / PagerDuty | アラート追加 |
| X-3 | - | **Secret Manager** (Langfuse auth / API キー) + **Workload Identity** (SA 連携) | 認証基盤追加 |
| X-4 | `.github/workflows/pr-tests.yml` | 同じ (共通) | 変更なし |

### 3.3 GCS バケット構成

単一バケット or 用途別に分割:

```
gs://{project}-analytics-raw/
  raw/                         # アプリが直接書く (サイドカー経由)
    service_name={svc}/
      event_type={et}/
        dt={YYYY-MM-DD}/
          hour={HH}/
            *.jsonl.gz
  uploaded/                    # Load Job 取込済みの退避先
    同構造
  dead_letter/                 # 取込失敗 (スキーマ違反等)
    同構造
  payloads/                    # 大きなコンテンツ (8KB 超)
    {service_name}/
      {YYYY-MM-DD}/
        {event_id}.{ext}
```

**ライフサイクル** (設計書 §8.2):

| ストレージクラス | 遷移タイミング | 用途 |
|---|---|---|
| Standard | 0〜30 日 | ホット分析 |
| Nearline | 30〜90 日 | 月次集計 / 問合せ対応 |
| Coldline | 90 日〜1 年 | 監査 / 再計算 |
| Archive / 削除 | 1 年〜 | コンプライアンス or 削除 |

### 3.4 BigQuery データセット構成

`scripts/gcp_bootstrap.sh` が以下を idempotent に作成する:

```
{project}.analytics_raw
  └─ agent_events_external      (external table, Hive partitioning AUTO)
       sourceUris: gs://{bucket}/uploaded/*
       partition columns: service_name / event_type / dt / hour
       autodetect schema: ON

{project}.analytics_staging      (dbt-bigquery が view で物理化)
  ├─ stg_agent_events
  ├─ stg_llm_calls
  ├─ stg_messages
  └─ stg_tool_invocations

{project}.analytics_marts        (dbt-bigquery が table で物理化)
  ├─ mart_daily_agent_metrics
  ├─ mart_cache_efficiency
  └─ mart_delivery_health
```

データセット名は env (`ANALYTICS_BQ_RAW_DATASET` 等) で変更可能。命名規則は `dbt/macros/generate_schema_name.sql` で `analytics_{custom}` 固定にしている。

**コスト最適化の鉄則** (設計書 §14.3):

- **ストリーミング挿入は使わない** → GCS Hive partitioning + external table で読む (Load Job 不要)。データ量が増えたら native table 化 + パーティション/クラスタ追加を検討
- **パーティション + クラスタ必須** → 1 クエリ 100GB 以上スキャンする場合はプルーニング確認
- **Langfuse も BQ にエクスポート** → 長期保存は BQ、Langfuse は直近 30〜90 日のみ保持

**外部テーブル → ネイティブテーブルへの将来移行** (Phase 5.x):
- 現状: GCS Hive partitioning autodetect で external 参照 (Load Job ゼロ)
- 移行先: Cloud Workflows で hourly Load Job → `analytics_raw.agent_events` (PARTITION BY DATE(event_timestamp), CLUSTER BY service_name, event_type)
- 切替は `dbt/models/raw/sources.yml` の `identifier` を差替えるだけで済む

### 3.5 オーケストレーション

```
Cloud Scheduler (cron)
    │ 1 時間ごと
    ▼
Cloud Workflows
    ├─ Step 1: GCS raw/ から Load Job 発行 → BigQuery raw.agent_events に追記
    │          (失敗時 → dead_letter/ へ移動 + Slack 通知)
    ├─ Step 2: dbt run --select staging+ (増分)
    ├─ Step 3: dbt test
    └─ Step 4: 成功時 raw/ → uploaded/ へ移動
    │
    ▼
Cloud Run Jobs (dbt コンテナ)
    - dbt-bigquery + Workload Identity で BigQuery に認証
    - コンテナは analytics-platform の Dockerfile から同じ SHA で build
```

**日次ジョブ** (追加):
- `dbt run --select marts` フル rebuild (Phase 6+ で incremental 化)
- Enrichment (content_summary / content_keywords 生成)

### 3.5.1 dbt Cloud Run Job コンテナ (実装済)

`Dockerfile` から作る image を Artifact Registry に push し、Cloud Run Jobs で `dbt run` / `dbt test` を実行する。Workload Identity 経由で BigQuery に認証。

#### 構成

```
Dockerfile                  ← multi-stage build (builder=uv sync / runtime=python:3.12-slim)
scripts/docker_entrypoint.sh ← run-and-test / run / test / parse / shell サブコマンド
cloudbuild.yaml             ← Cloud Build pipeline (build → smoke parse → push)
.dockerignore               ← .venv / data / .git 等を image に持ち込まない
Makefile                    ← docker-build / docker-parse / docker-run / docker-test / docker-shell
```

#### ローカルで動かす

```bash
# 1. build
make docker-build           # → analytics-platform-dbt:local

# 2. 接続なしの sanity check (env 必須)
ANALYTICS_BQ_PROJECT=test-project make docker-parse

# 3. 実 BQ で実行 (gcloud ADC を mount)
gcloud auth application-default login
ANALYTICS_BQ_PROJECT=youyaku-ai \
ANALYTICS_BQ_LOCATION=US \
make docker-run

# 4. デバッグ
make docker-shell
```

イメージは非 root (`runner` UID 10001) で動き、PID 1 は `tini`。`SIGTERM` を child の `dbt` に伝搬するため、Cloud Run Job のタイムアウトでも graceful に終わる。

#### Artifact Registry に push

```bash
# 事前: gcloud artifacts repositories create analytics-platform \
#   --repository-format=docker --location=us-central1

gcloud builds submit \
  --config analytics-platform/cloudbuild.yaml \
  --substitutions=_LOCATION=us-central1,_REPO=analytics-platform \
  analytics-platform/
```

build → image 内で `dbt parse` smoke → `${SHORT_SHA}` と `latest` の 2 タグで push。

#### Cloud Run Jobs として登録

```bash
# image の host は profile に応じて差替
IMAGE="us-central1-docker.pkg.dev/${GCP_PROJECT}/analytics-platform/analytics-platform-dbt:latest"

gcloud run jobs deploy analytics-platform-dbt \
  --image="${IMAGE}" \
  --region=us-central1 \
  --service-account="sa-dbt@${GCP_PROJECT}.iam.gserviceaccount.com" \
  --set-env-vars="ANALYTICS_BQ_PROJECT=${GCP_PROJECT},ANALYTICS_BQ_LOCATION=US,ANALYTICS_BQ_DEFAULT_DATASET=analytics_staging" \
  --task-timeout=30m \
  --max-retries=2

# 即時実行 (Cloud Workflows から呼ばれる前の手動確認用)
gcloud run jobs execute analytics-platform-dbt --region=us-central1 --wait
```

`sa-dbt` (Workload Identity) には `roles/bigquery.user` + `roles/bigquery.dataEditor` (analytics_staging / analytics_marts に対して) を付与する (§3.6)。

### 3.6 IAM / セキュリティ境界

コンポーネント単位の Service Account:

| SA | 権限 | 用途 |
|---|---|---|
| `sa-uploader` | `roles/storage.objectAdmin` on `{bucket}/raw/`, `{bucket}/payloads/` | アプリ / サイドカーからの GCS 書込 |
| `sa-loader` | `roles/storage.objectViewer` + `roles/bigquery.dataEditor` | Cloud Workflows の GCS → BQ Load |
| `sa-dbt` | `roles/bigquery.user` + `roles/bigquery.dataEditor` on staging/marts | dbt 実行 |
| `sa-langfuse` | `roles/cloudsql.client` + `roles/storage.objectAdmin` on Langfuse bucket | Langfuse Pod |
| `sa-alerter` | `roles/monitoring.viewer` + Pub/Sub publisher | アラート転送 |

**秘匿情報**:
- Langfuse の DB パスワード / Anthropic API Key などは **Secret Manager** に保存
- Pod は Workload Identity で SA を受け取り、Secret Manager から読む

**ネットワーク** (推奨):
- GKE を **Private cluster** にし、Cloud NAT で外部 LLM API に出る
- Langfuse UI は **IAP (Identity-Aware Proxy)** 経由で SSO
- BigQuery / GCS は **VPC Service Controls** でプロジェクト境界を明示

### 3.7 信頼性 (設計書 §9)

- **アプリ → サイドカー**: ローカル FS 経由 (メモリバッファ + ファイル) で同期呼出を軽く保つ
- **サイドカー → GCS**: `tenacity` の指数バックオフ (1→2→4→8→16 秒、最大 5 回) → 失敗時 `dead_letter/`
- **GCS → BQ**: Cloud Workflows のリトライ (step 単位) → 失敗時 Slack 通知
- **冪等性**: `event_id` (UUID v7) + `ingested_at` で重複検知。Load Job を 2 回投げても MERGE or 後段 dbt で排除
- **バッファ監視**: アプリ内バッファ滞留量を Cloud Monitoring の custom metric に出す

### 3.8 ローカル → GCP 移行手順 (想定)

| 手順 | 内容 | 備考 |
|---|---|---|
| 1 | GCP プロジェクト + VPC + GKE (Autopilot 推奨) + Artifact Registry を準備 | Terraform 管理 |
| 2 | Langfuse on GKE を Helm chart でデプロイ (Cloud SQL / Memorystore / GCS を紐付け) | 設計書 §4.2 |
| 3 | GCS バケット 3 種 + ライフサイクルルールを作成 | §3.3 |
| 4 | BigQuery データセット `analytics_raw` / `analytics_staging` / `analytics_marts` を作成 | §3.4 |
| 4 | `make gcp-bootstrap` で BQ datasets + external table を作成 | `scripts/gcp_bootstrap.sh` (✅ 実装済) |
| 5 | `PayloadWriter` / `UploadTransport` の GCS 実装を追加 (`analytics_platform/observability/content_gcs.py` 等) | ✅ 実装済。Protocol 実装だけで L1/L2 アプリコードは無変更 |
| 6 | `dbt/profiles.yml` に `target: gcp` を追加 (`dbt-bigquery` adapter) | ✅ 実装済 (cross-DB macros + adapter dispatch、§3.0.1 参照) |
| 7 | Cloud Run Jobs のコンテナ image を build & push (dbt 用) | ✅ 実装済 (`Dockerfile` + `cloudbuild.yaml`、§3.5.1 参照)。Uploader 用は GCSTransport で in-process なため省略 |
| 8 | Cloud Scheduler + Cloud Workflows を設定 | §3.5 (未着手) |
| 9 | Cloud Monitoring のアラートポリシーを作成 (エラー率 / バッファ滞留 / Load 失敗) | (未着手) |
| 10 | アプリの `.env` を `ENV=gcp` + Langfuse endpoint に切替、デプロイ | 計装コードは再ビルド不要 |

**カットオーバー**:
- 両基盤を並走 (shadow mode) でデータ整合性を 1〜2 週間確認してから正式切替
- 並走時は `event_id` / `trace_id` 重複は後段 dbt で排除 (Raw 層は append-only でも OK)

### 3.9 Phase 6+ の拡張余地 (想定)

| Phase | 追加する GCP サービス | 用途 |
|---|---|---|
| Phase 6 検索 | **BigQuery Search Index** (`CREATE SEARCH INDEX`) | `content_preview` / `content_summary` の全文検索 |
| Phase 6 検索 | **Vertex AI Vector Search** or **BigQuery VECTOR_SEARCH** | セマンティック検索 |
| Phase 6 Enrichment | **Cloud Run Jobs** (Haiku 呼出) | `content_summary` / `content_keywords` の後段付与 |
| Phase 7 BI | **Looker Studio** (外部向け) / **Metabase on GKE** (社内) | ダッシュボード |
| Phase 8 アラート | **Cloud Monitoring** + **Pub/Sub** + **PagerDuty**, **Grafana Alerting** | SLO ベース通知 |
| スケール拡大時 | **Pub/Sub** + **Dataflow** | 千件/秒超のストリーミング取込 (§9.4) |

---

## 4. コード構成

```
analytics-platform/
├── analytics_platform/          # 外部から import されるライブラリ名前空間
│   ├── config.py                # pydantic-settings で .env を読む
│   ├── observability/
│   │   ├── schemas.py           # Pydantic discriminated union (event_type 7 種)
│   │   ├── hashing.py           # sha256:<hex> 強制
│   │   ├── context.py           # OTel Context → trace_id / span_id (W3C 形式)
│   │   ├── tracer.py            # TracerProvider 初期化 (Phoenix / Langfuse)
│   │   ├── logger.py            # structlog 設定 (trace_id 自動注入)
│   │   ├── content.py           # ContentRouter (inline / URI 振り分け)
│   │   ├── analytics_logger.py  # AnalyticsLogger 本体 (バッファ + flush)
│   │   └── sinks/
│   │       └── file_sink.py     # Hive パーティション JSONL シンク
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

## 5. 主要な設計判断

設計書 (セッション冒頭に貼付) を参照。本 PR で特に重視した点:

- **Discriminated Union**: `event_type` ごとの必須フィールドを Pydantic が emit 時点で強制
- **Hive パーティション**: `service_name=.../event_type=.../dt=.../hour=.../` を `RotatingFileSink` がそのまま掘る。DuckDB `read_json_auto(..., hive_partitioning=true)` が即読める
- **`sha256:<hex>` prefix 強制**: `content_hash` / `input_args_hash` 等は `sha256_prefixed()` で必ず整形
- **`ingested_at` は dbt Staging 層で付与**: アプリ側では発行しない (設計書 §6.2 注記)
- **ローカル擬似 GCS**: `data/raw/ → uploaded/ → dead_letter/` の 3 段構成で、将来 GCS Uploader に差し替え可能
- **大きなコンテンツ**: 8KB (既定) 超は `data/payloads/{service}/{dt}/{event_id}.{ext}` に退避し `file://...` URI を付与

---

## 6. 主要 API

### 6.1 AnalyticsLogger

```python
from analytics_platform.observability.analytics_logger import AnalyticsLogger
from analytics_platform.observability.sinks.file_sink import RotatingFileSink

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

### 6.2 ContentRouter

```python
from analytics_platform.observability.content import ContentRouter, LocalFilePayloadWriter

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

### 6.3 tracer.setup_tracer

```python
from analytics_platform.observability.tracer import setup_tracer

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

## 7. 実装フェーズ進捗

設計書 §15 の 9 フェーズ + 各エージェントへの計装状況。

### 7.1 設計書フェーズ

| Phase | 内容 | 状態 | 主要 PR / 参照 |
|---|---|---|---|
| **Phase 1** | ローカル環境 (Phoenix + DuckDB + dbt-duckdb 雛形) | ✅ 完了 | PR #24 |
| **Phase 2** | OTel 計装ライブラリ + AnalyticsLogger | ✅ 完了 | PR #24 / `analytics_platform/observability/` |
| **Phase 3** | JSONL スキーマ + コンテンツ格納戦略 | ✅ 完了 | PR #24 / `schemas.py` / `content.py` |
| **Phase 4** | dbt モデル (raw / staging / marts) | ✅ 完了 | PR #24 / `dbt/models/` |
| **Phase 5 (進行中)** | GCP 環境 — GCS Uploader / Payload + dbt-bigquery + Cloud Run Job 化 | 🔶 部分実装 (Uploader / Payload / dbt-bigquery / dbt コンテナ完了。Workflows / Langfuse on GKE 未着手) | §3.0 / §3.0.1 / §3.4 / §3.5.1 |
| Phase 6 | 検索基盤 (BigQuery Search Index + Enrichment / Vector Search) | ⬜ 未着手 | §3.9 |
| Phase 7 | ダッシュボード (Metabase + Looker Studio) | ⬜ 未着手 | §3.9 |
| Phase 8 | アラート (Grafana Alert + Cloud Monitoring) | ⬜ 未着手 | §3.9 |
| Phase 9 | 継続評価・セマンティック検索 (LLM-as-a-Judge / Vector Search) | ⬜ 未着手 | 設計書 §15 |

### 7.2 既存エージェントへの計装状況

| エージェント | 状態 | PR |
|---|---|---|
| `stock-analysis-agent` | ✅ 完了 (Claude Agent SDK のメッセージストリームから llm_call / tool_invocation / message を抽出) | PR #26 |
| `lifeplanner-agent` | ✅ 完了 (Anthropic / Vertex 両クライアント + 6 ルートに business_event / error_event) | PR #27 |
| `kanie-lab-agent` | ⬜ 未着手 (フロントエンド込みのため別 PR で対応) | - |

---

## 8. 環境変数一覧

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
