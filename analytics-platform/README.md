# analytics-platform

エージェントシステム (Claude Agent SDK / MCP / FastAPI 等) から発生する
**チャット履歴・トレース・メトリクス・業務イベント**を一元収集する分析基盤。
モノレポ内の他エージェント (lifeplanner / piyolog / stock-analysis 等) から
path dep として取り込まれ、計装 SDK と JSONL → dbt パイプラインを共通提供する。

> **Status**: Phase 1-4 完了 / Phase 5 大部分実装 (GCS / BigQuery / Workflows / Terraform / Monitoring)、Step 2 Langfuse on GKE と Step 10 全エージェント切替が未着手

設計詳細 (アーキテクチャ / 機能要件 / NFR / ADR-lite / Roadmap) は
[`docs/DESIGN.md`](docs/DESIGN.md) を参照。本 README は「動かす / 使う」観点に絞る。

---

## 0. Quickstart

### 0.1 前提

| ツール | バージョン | 備考 |
|---|---|---|
| Python | 3.12+ | `pyproject.toml` で指定 |
| uv | 最新 | パッケージ管理 |
| Docker / Docker Compose | 任意 | Phoenix UI を立てる場合のみ |
| gcloud CLI | 最新 | GCP backend を使う場合のみ |

### 0.2 セットアップ

```bash
cd agent_monorepo/analytics-platform

cp .env.example .env

make install
```

### 0.3 Phoenix 起動 (任意)

```bash
make phoenix-up           # → http://localhost:6006
make phoenix-down
```

Phoenix を起動しなくても OTel Exporter は失敗ログを出すだけでアプリは動作する
(JSONL 出力のみ確認したい場合はスキップ可)。

### 0.4 デモを走らせる

```bash
# 業務ログ (JSONL) を生成 → dbt で DuckDB に取り込む
make etl

# DuckDB を直接開いて確認
uv run python -c "import duckdb; print(duckdb.connect('data/analytics.duckdb').sql('SELECT event_type, COUNT(*) FROM stg_agent_events GROUP BY 1').df())"
```

### 0.5 テスト・静的解析

```bash
make test          # pytest (~93 tests)
make lint          # ruff check
make check         # lint + test
```

### 0.6 ライブラリとして他エージェントから使う

`uv` の path dependency で取り込む:

```toml
# 消費側エージェントの pyproject.toml
[project]
dependencies = ["analytics-platform"]

[tool.uv.sources]
analytics-platform = { path = "../analytics-platform" }
```

書き出し先 (`ANALYTICS_DATA_DIR` 既定 `./data`) は env で上書き可能。
複数エージェントが同じディレクトリに書いても、`service_name` が Hive
パーティションキーになるため衝突しない。

---

## 1. 主要 API

詳細な API 解説と event_type 一覧は [`docs/DESIGN.md`](docs/DESIGN.md) (§5 / §6) 参照。

### 1.1 AnalyticsLogger

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

`trace_id` / `span_id` は OTel Context から自動取得 (スパンが無ければ None)。

### 1.2 ContentRouter

8KB (既定) 超のコンテンツは payload ファイルへ退避し、event には URI を入れる。

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

GCP backend では `build_payload_writer()` で `GCSPayloadWriter` に切替 (§3.1)。

### 1.3 tracer.setup_tracer

プロセス起動時に 1 度だけ呼ぶ。OTLP endpoint は env で Phoenix / Langfuse を切替。

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

## 2. 環境変数

主要なものだけ。詳細は [`.env.example`](.env.example) 参照。

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

GCP backend を有効化する env は §3 を参照。

---

## 3. GCP backend セットアップ

ローカル ↔ GCP は **env 1 行 (`ANALYTICS_STORAGE_BACKEND=gcs`)** で切替可能。
consumer 側のアプリコードは無変更。詳細は
[`docs/DESIGN.md`](docs/DESIGN.md) §3 / §10 (ADR-lite) 参照。

### 3.1 ストレージ切替 env

| 環境変数 | 既定 | 説明 |
|---|---|---|
| `ANALYTICS_STORAGE_BACKEND` | `local` | `local` \| `gcs`。`gcs` 指定時のみ下記が効く |
| `ANALYTICS_GCS_BUCKET` | — | GCS バケット名 (`gcs` 時必須、未設定なら local にフォールバック + 警告) |
| `ANALYTICS_GCS_RAW_PREFIX` | `uploaded/` | raw JSONL の upload prefix |
| `ANALYTICS_GCS_PAYLOAD_PREFIX` | `payloads/` | 大容量 payload の prefix |
| `ANALYTICS_GCP_PROJECT` | (ADC から自動推論) | GCP プロジェクト ID |

consumer 側の使い方:

```python
from pathlib import Path
from analytics_platform.gcp_config import build_payload_writer, build_upload_transport

writer = build_payload_writer(local_root=Path("./data/payloads"))
router = ContentRouter(writer=writer, inline_threshold_bytes=8192)

transport = build_upload_transport(raw_root=Path("./data/raw"))
uploader = LocalUploader(
    raw_root=Path("./data/raw"),
    uploaded_root=Path("./data/uploaded_noop"),
    dead_letter_root=Path("./data/dead_letter"),
    transport=transport,
)
```

インストール: `uv sync --extra gcs` (optional `[gcs]` extra、`google-cloud-storage` を含む)。

### 3.2 BigQuery / dbt-bigquery

dbt は cross-DB マクロ + adapter dispatch で `--target local` (DuckDB) / `--target gcp` (BigQuery) を切替可能。

| 環境変数 | 既定 | 説明 |
|---|---|---|
| `ANALYTICS_BQ_PROJECT` | — | GCP project id (必須) |
| `ANALYTICS_BQ_LOCATION` | `US` | BQ location |
| `ANALYTICS_BQ_RAW_DATASET` | `analytics_raw` | raw external table 配置先 |
| `ANALYTICS_BQ_STAGING_DATASET` | `analytics_staging` | staging dataset |
| `ANALYTICS_BQ_MARTS_DATASET` | `analytics_marts` | marts dataset |
| `ANALYTICS_BQ_DEFAULT_DATASET` | `analytics_staging` | profiles.yml の `dataset` |
| `ANALYTICS_BQ_RAW_TABLE` | `agent_events_external` | raw external table 名 |

セットアップ手順 (初回のみ):

```bash
# 1. dbt-bigquery + google-cloud-bigquery を入れる
make install-gcp

# 2. ADC 認証 (ローカルから動かす場合)
gcloud auth login
gcloud auth application-default login
gcloud config set project "${ANALYTICS_BQ_PROJECT}"

# 3. BQ dataset + external table を作成 (idempotent)
make gcp-bootstrap
```

実行:

```bash
make dbt-parse-bq    # 接続なしの SQL sanity check
make dbt-run-bq      # BQ にクエリが走る
make dbt-test-bq
```

cross-DB マクロの一覧と raw 層の物理化方式の差分は [`docs/DESIGN.md`](docs/DESIGN.md) §10 (ADR-lite) 参照。

### 3.3 Terraform IaC

`terraform/` 配下で **GCS バケット / BigQuery dataset / Artifact Registry / Service Accounts + IAM / Cloud Monitoring alert** を管理。Cloud Run Job / Workflows / Scheduler は CI/CD で頻繁に更新するため shell script で管理し、静的なデータ基盤と IAM だけを TF で固める方針。

```bash
# 1. state バケットを手動作成 (chicken-and-egg)
gsutil mb -p $PROJECT -l US gs://${PROJECT}-tfstate
gsutil versioning set on gs://${PROJECT}-tfstate

# 2. tfvars / backend.tf を準備
cd analytics-platform/terraform
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars   # project_id を埋める

# 3. apply
cd ..
make tf-init && make tf-plan && make tf-apply
make tf-output-env         # → analytics-platform/.env.gcp
```

詳細手順 / drift 検知 / import / トラブルシュートは [`terraform/README.md`](terraform/README.md) 参照。

### 3.4 オーケストレーション

```
Cloud Scheduler ──▶ Cloud Workflows (analytics-platform-dbt-pipeline)
                       │ workflows/dbt_pipeline.yaml
                       ▼
                    Cloud Run Jobs (analytics-platform-dbt)
                       Dockerfile / scripts/docker_entrypoint.sh
```

```bash
# Workflow + Scheduler をデプロイ (idempotent)
ANALYTICS_GCP_PROJECT=${ANALYTICS_GCP_PROJECT} \
ANALYTICS_SCHEDULE_CRON="0 * * * *" \
make deploy-orchestration

# 手動トリガで疎通確認
make trigger-workflow
```

dbt image の Cloud Build push:

```bash
gcloud builds submit \
  --config analytics-platform/cloudbuild.yaml \
  --substitutions=_LOCATION=us-central1,_REPO=analytics-platform \
  analytics-platform/
```

Cloud Monitoring アラート (Workflow FAILED / dbt Job failed / dbt Job slow + email channel) は `terraform/monitoring.tf` で管理。`notification_email` を `terraform.tfvars` に書いて `tf-apply`。

---

## 4. コード構成

```
analytics-platform/
├── analytics_platform/          # 外部から import されるライブラリ名前空間
│   ├── observability/           # tracer / logger / schemas / content / sinks
│   ├── uploader/                # local_uploader / gcs transport
│   └── gcp_config.py            # env 駆動の factory (PayloadWriter / UploadTransport)
├── dbt/
│   ├── models/                  # raw / staging / marts (cross-DB)
│   ├── macros/                  # cross_db.sql / generate_schema_name.sql
│   └── profiles.yml             # local (DuckDB) / gcp (BigQuery)
├── terraform/                   # GCS / BQ / IAM / Monitoring (§3.3)
├── workflows/                   # Cloud Workflows YAML
├── scripts/                     # demo_emit / run_etl / gcp_bootstrap / deploy_orchestration
├── docs/
│   └── DESIGN.md                # システム全体設計書
├── tests/                       # pytest (~93 tests)
├── Dockerfile                   # dbt Cloud Run Job image
├── cloudbuild.yaml
├── docker-compose.yml           # Phoenix
├── Makefile
├── pyproject.toml
└── .env.example
```

---

## 5. 関連ドキュメント

- [`docs/DESIGN.md`](docs/DESIGN.md) — システム全体設計 (機能要件 / NFR / 6 レイヤーアーキ / GCP 構成 / Roadmap / ADR-lite / 用語集)
- [`terraform/README.md`](terraform/README.md) — Terraform 詳細手順 (state バケット / 初回 apply / drift / import / 削除)
- [`../docs/PROPOSALS/`](../docs/PROPOSALS/) — モノレポ共通の per-feature proposal / ADR
- [`../docs/MIGRATION_PLAN.md`](../docs/MIGRATION_PLAN.md) — ドキュメント refactoring 全体計画
- 連携先エージェント: `stock-analysis-agent` (PR #26 計装済) / `lifeplanner-agent` (PR #27 計装済) / `piyolog-analytics` / `tech-news-agent` / `hotcook-agent` / `kanie-lab-agent` (未着手)
