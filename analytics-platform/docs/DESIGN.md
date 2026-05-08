# analytics-platform 設計書

| | |
|---|---|
| **Version** | 1.0 |
| **最終更新** | 2026-05-08 |
| **Status** | Active (Phase 1-4 完了 / Phase 5 大部分実装) |
| **Owner** | @kurama554101 |
| **Type** | 共通基盤 (path dep として複数エージェントから参照) |
| **README** | [`../README.md`](../README.md) |

## 変更履歴

| 日付 | Version | 変更内容 |
|---|---|---|
| 2026-04 | (初版) | README に集約 |
| 2026-05-08 | 1.0 | `docs/SYSTEM_DESIGN_TEMPLATE.md` 準拠で設計内容を README から分離 (Quickstart + 主要 API + 環境変数は README に残置) |

---

## 0. Executive Summary

エージェントシステム (Claude Agent SDK / MCP / FastAPI 等) から発生する
**チャット履歴・トレース・メトリクス・業務イベント**を一元収集・分析する基盤。
モノレポ内の複数エージェントから path dep として参照され、計装 SDK
(`AnalyticsLogger` / `tracer.setup_tracer` 等) を共通提供する。

- **ローカル**: Phoenix + OTel + JSONL + DuckDB + dbt
- **GCP**: GCS (raw JSONL) + BigQuery (external table + dbt models) + Cloud Workflows + Scheduler、Langfuse は GKE 計画中
- **切替**: `ANALYTICS_STORAGE_BACKEND=local|gcs` の env 1 行で consumer 側コード変更ゼロ

---

## 1. 目的・スコープ

### 1.1 目的

- 複数エージェントの計装を **同一 SDK** で完結させる (重複実装の排除)
- ローカル / GCP の **コード変更ゼロ切替** を実現
- LLM 呼出 / 業務イベント / エラー / OTel スパンを **同じ `event_id` 軸**で突合可能にする
- セキュリティ・コスト配慮: PII raw は送らず、必要時 ContentRouter で外部ストレージ (GCS) に payload を逃がして event 本体は軽量に

### 1.2 想定ユーザー

| 種別 | 内容 |
|---|---|
| 主要 | モノレポ内の各エージェント (consumer 側、path dep で取り込み) |
| 副次 | 開発者 / 運営者 (BigQuery / DuckDB で直接クエリ、Phoenix / Langfuse でトレース確認) |
| 想定外 | 商用 SaaS としての提供、複数組織テナント |

### 1.3 Non-Goals

- 単独エージェントとしての提供 (= ライブラリ + 運用基盤、UI なし)
- 外部 SaaS 観測サービス (Datadog / New Relic 等) との競合
- リアルタイムストリーミング処理 (バッチ集計が前提、JSONL → upload → BQ)
- 複数組織テナント分離 (個人運用、複数 service_name で軽い分離のみ)

---

## 2. 機能要件

| ID | 機能 | 状態 | Phase |
|---|---|---|---|
| F1 | OTel SDK 計装 (Phoenix / Langfuse OTLP) | ✅ 実装済 | Phase 1-2 |
| F2 | AnalyticsLogger (Pydantic 検証 + リングバッファ + 非同期 flush) | ✅ 実装済 | Phase 2 |
| F3 | 7 種の event_type (llm_call / business_event / error_event / conversation_event / tool_invocation / message / span_event) | ✅ 実装済 | Phase 3 |
| F4 | ContentRouter (inline / URI 振り分け、8KB 閾値) | ✅ 実装済 | Phase 3 |
| F5 | RotatingFileSink (Hive パーティション JSONL) | ✅ 実装済 | Phase 2 |
| F6 | LocalUploader (raw → uploaded、失敗 dead_letter) | ✅ 実装済 | Phase 2 |
| F7 | dbt-duckdb (raw → staging → marts) | ✅ 実装済 | Phase 4 |
| F8 | dbt-bigquery 対応 (cross-DB マクロ + adapter dispatch) | ✅ 実装済 | Phase 5 |
| F9 | GCS Backend (`ANALYTICS_STORAGE_BACKEND=gcs` で env 切替) | ✅ 実装済 | Phase 5 |
| F10 | Terraform IaC (GCS / BQ / Artifact Registry / IAM) | ✅ 実装済 | Phase 5 |
| F11 | Cloud Workflows + Scheduler (dbt 定期実行) | ✅ 実装済 | Phase 5 |
| F12 | Cloud Monitoring アラート (Workflow FAILED / dbt slow) | ✅ 実装済 | Phase 5 |
| F13 | Langfuse on GKE | 📋 計画 | Phase 5 残 |
| F14 | BigQuery Search Index + Vector Search | 📋 計画 | Phase 6 |
| F15 | Metabase / Looker Studio ダッシュボード | 📋 計画 | Phase 7 |
| F16 | LLM-as-a-Judge / セマンティック検索 | 📋 計画 | Phase 9 |

---

## 3. 非機能要件 (NFR)

### 3.1 性能

| 項目 | 目標 |
|---|---|
| `AnalyticsLogger.emit` のレイテンシ | < 1 ms (in-memory queue + 非同期 flush) |
| RotatingFileSink の rotate 判定 | < 50 ms |
| dbt staging build (1 日分) | < 30 秒 |
| BQ external table クエリ (1 ヶ月分) | < 10 秒 |

### 3.2 可用性

- 共通基盤のため可用性は consumer 側の挙動に影響: emit 失敗時は **`NoOpSink` フォールバック** で consumer を落とさない
- GCP backend (`gcs`): Cloud Run Job + Workflow + Scheduler の構成で可用性 99.9% 想定 (Cloud Workflows の SLA に従う)
- ローカル backend: ファイルシステムに依存、`ANALYTICS_DATA_DIR` の容量逼迫がリスク

### 3.3 セキュリティ

- `service_name` でテナント分離 (Hive パーティションキー)
- GCP backend: Workload Identity Federation で `sa-uploader` SA、raw / payloads / dead_letter bucket への `objectAdmin` のみ付与
- 秘密情報 (API キー / トークン) は **emit 対象外** (consumer 側で sha256 hash 化)
- BQ クエリは IAM で `analytics_marts` (利用側) と `analytics_raw` (admin) を分離可
- Langfuse UI は IAP (Identity-Aware Proxy) 経由で SSO (将来)
- BigQuery / GCS は VPC Service Controls でプロジェクト境界明示 (推奨)

### 3.4 コスト

| 項目 | 目標 | 備考 |
|---|---|---|
| GCS storage (uploaded/) | < 1 GB / 月 (全エージェント合計) | lifecycle 90 日で archive、365 日で delete |
| BigQuery クエリ (dbt) | < 10 GB / 月 スキャン | external table → staging materialized for 90 日のみ |
| Cloud Run Job (dbt) | 月 ~30 回 × 5 分 = 2.5 時間 | 0.5 vCPU × 1GB、月数百円 |
| Cloud Workflows + Scheduler | ~30 実行 / 月 | 無料枠内 |

### 3.5 プライバシー / データ保持

- consumer 側の判断: PII (LINE userId / 取引明細など) は **sha256 hash 化** または `content_hash` のみ送信
- raw payload (大容量) は ContentRouter が GCS payloads/ に書く、保持 30 日 (lifecycle)
- raw JSONL (uploaded/): GCS で 365 日保持 (再処理用)
- BigQuery: dbt staging は 90 日保持、marts は永続

### 3.6 キャパシティ

- 想定: モノレポ内 5〜10 エージェント、1 日あたり 10,000 events 程度
- 1 event の典型サイズ: 1〜5 KB (raw payload は ContentRouter で別経路)
- 1 日の JSONL: 10〜50 MB / day → 1 ヶ月 ~1.5 GB
- BigQuery 無料枠 1 TB/月 のうち、dbt + ad-hoc で 10 GB 程度

### 3.7 保守性 / テスト性

- Pydantic schemas で全 event_type を強制 (`BusinessEvent` / `LlmCall` / `ErrorEvent` 等)
- ローカル / GCP 切替は `ANALYTICS_STORAGE_BACKEND` 1 行で OK (consumer 側コード変更ゼロ)
- dbt の SQL 妥当性は `dbt parse` で CI チェック可
- consumer 計装の "ground truth" は `tests/test_analytics_logger.py` 等の統合テスト

---

## 4. データモデル

### 4.1 イベントスキーマ (Pydantic Discriminated Union)

`analytics_platform/observability/schemas.py` で 7 種類の `event_type` を厳格に型付け:

| event_type | 主要フィールド |
|---|---|
| `llm_call` | llm_provider / llm_model / input_tokens / output_tokens / cache_read_tokens / latency_ms |
| `business_event` | business_domain / action / resource_type / resource_id / attributes |
| `error_event` | error_type / error_message / error_category / is_retriable |
| `conversation_event` | conversation_phase / agent_id / initial_query_hash |
| `tool_invocation` | tool_name / input_args_hash / output_summary / latency_ms |
| `message` | message_id / message_role / message_index / content_text or content_uri |
| `span_event` | span_name / attributes (OTel と同期) |

**共通フィールド** (全 event 必須): `event_id` / `event_timestamp` / `service_name` / `service_version` / `environment` / `trace_id` / `span_id` / `user_id` / `session_id` / `severity`

### 4.2 dbt 3 層 (raw / staging / marts)

```
raw                staging               marts
─────────          ─────────             ─────────
agent_events  →   stg_agent_events  →   mart_daily_agent_metrics
                  stg_llm_calls          mart_cache_efficiency
                  stg_messages           mart_delivery_health
                  stg_tool_invocations
```

- **raw**: GCS / ローカル FS の JSONL を物理化 (DuckDB は table、BQ は external table を view 参照)
- **staging**: 共通フィールド正規化 + `ingested_at` 付与 + TIMESTAMPTZ 化
- **marts**: KPI テーブル (永続)

### 4.3 GCS バケット構成

```
gs://{project}-analytics-raw/
  raw/                         # アプリが直接書く (サイドカー経由)
    service_name={svc}/
      event_type={et}/
        dt={YYYY-MM-DD}/
          hour={HH}/
            *.jsonl.gz
  uploaded/                    # Load Job 取込済みの退避先
  dead_letter/                 # 取込失敗 (スキーマ違反等)
  payloads/                    # 大きなコンテンツ (8KB 超)
    {service_name}/{YYYY-MM-DD}/{event_id}.{ext}
```

**ライフサイクル**:

| ストレージクラス | 遷移タイミング | 用途 |
|---|---|---|
| Standard | 0〜30 日 | ホット分析 |
| Nearline | 30〜90 日 | 月次集計 / 問合せ対応 |
| Coldline | 90 日〜1 年 | 監査 / 再計算 |
| Archive / 削除 | 1 年〜 | コンプライアンス or 削除 |

### 4.4 BigQuery データセット構成

```
{project}.analytics_raw
  └─ agent_events_external      (external table, Hive partitioning AUTO)
       sourceUris: gs://{bucket}/uploaded/*
       partition columns: service_name / event_type / dt / hour
       autodetect schema: ON

{project}.analytics_staging      (dbt-bigquery が view で物理化)
  ├─ stg_agent_events / stg_llm_calls / stg_messages / stg_tool_invocations

{project}.analytics_marts        (dbt-bigquery が table で物理化)
  ├─ mart_daily_agent_metrics / mart_cache_efficiency / mart_delivery_health
```

**コスト最適化の鉄則**:
- ストリーミング挿入は使わない → GCS Hive partitioning + external table で読む (Load Job 不要)
- パーティション + クラスタ必須 → 1 クエリ 100GB 以上スキャン時はプルーニング確認
- Langfuse も BQ にエクスポート → 長期保存は BQ、Langfuse は直近 30〜90 日のみ保持

---

## 5. アーキテクチャ

### 5.1 ローカル範囲

```
[アプリ (demo_emit / agents)]
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
- **業務ログは常に 100% 書かれる**: OTel 側をサンプリングしても `trace_id` 突合は機能する
- **コンテンツの振り分け**: `content_inline_threshold_bytes` (既定 8KB) 以下なら `content_text` に直埋、超過なら `./data/payloads/` へ退避し `content_uri` に `file://...` を入れる

### 5.2 GCP 全体像

```
Agent Services (Cloud Run / GKE / GCE 上で稼働)
  OTel SDK ─────────┐
  AnalyticsLogger ──┐│
                    ││ JSONL    OTLP/HTTPS
                    ▼▼          ▼
            ┌────────────┐  ┌──────────────────────┐
            │ GCS        │  │ Langfuse on GKE       │
            │  raw /     │  │  (Helm chart、計画中)  │
            │  uploaded /│  │  - Cloud SQL          │
            │  payloads /│  │  - ClickHouse         │
            │  dead_letr │  │  - Memorystore Redis  │
            └────┬───────┘  │  - GCS storage        │
                 │ external │   IAP + Cloud LB     │
                 │ table    └─────┬────────────────┘
                 ▼                │ Export (nightly)
            ┌──────────────────────────────────────┐
            │ BigQuery                             │
            │  analytics_raw.agent_events_external │
            │  analytics_staging.stg_*             │
            │  analytics_marts.mart_*              │
            └────┬─────────────────────────────────┘
                 │ dbt-bigquery
                 │ (Cloud Run Jobs + Workflows)
                 ▼
            Metabase / Looker Studio / BQ Console

Orchestration (右側)
  Cloud Scheduler → Cloud Workflows → Cloud Run Jobs
                                      (dbt run + test)

Alerting
  Cloud Monitoring → Slack (FAILED / slow / dbt failure)
```

### 5.3 6 レイヤー構成 (差替境界)

各レイヤーは次のレイヤーにしか依存しない (上→下の一方向)。レイヤー間の境界は Protocol / dataclass で抽象化されており、GCP 版への差替ポイントもここ。

| # | レイヤー | 主要モジュール | 差替点 (GCP 版) |
|---|---|---|---|
| L1 | Producer (計装される側) | エージェント / `scripts/demo_emit.py` | 変更なし |
| L2-a | Tracer 初期化 | `analytics_platform/observability/tracer.py` | endpoint / headers / sampler を env で切替 |
| L2-b | Trace Context | `analytics_platform/observability/context.py` | 変更なし |
| L2-c | Structlog | `analytics_platform/observability/logger.py` | 変更なし |
| L2-d | Event Schema | `analytics_platform/observability/schemas.py` | 変更なし |
| L2-e | Hashing | `analytics_platform/observability/hashing.py` | 変更なし |
| **L2-f** | Content Router | `analytics_platform/observability/content.py` | `LocalFilePayloadWriter` → `GCSPayloadWriter` |
| L2-g | AnalyticsLogger | `analytics_platform/observability/analytics_logger.py` | 変更なし |
| L3-a | Trace Sink | (外部: Phoenix / Langfuse) | Phoenix Docker → Langfuse on GKE |
| **L3-b** | File Sink | `analytics_platform/observability/sinks/file_sink.py` | 同じ構造で GCS に直書き sink を追加可能 |
| **L4** | Uploader | `analytics_platform/uploader/local_uploader.py` | `LocalMoveTransport` → `GCSTransport` |
| **L5** | Transform (dbt) | `dbt/models/` | `dbt-duckdb` → `dbt-bigquery` (cross-DB マクロで吸収) |
| L6-a | Query | DuckDB CLI / Python `duckdb` | BigQuery クライアント |
| L6-b | Viz | (Phase 7 予定) | Metabase / Looker Studio |

GCP 拡張時に差し替えるのは **太字の 4 箇所 (L2-f / L3-b / L4 / L5)** のみ、上位アプリコードは無変更。

### 5.4 主要モジュール (コード構成)

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
│   │   └── sinks/file_sink.py   # Hive パーティション JSONL シンク
│   └── uploader/local_uploader.py  # raw → uploaded (失敗は dead_letter)
├── dbt/
│   ├── models/{raw,staging,marts}/
│   ├── macros/cross_db.sql      # DuckDB ↔ BQ 文法差吸収
│   └── macros/generate_schema_name.sql
├── scripts/
│   ├── demo_emit.py / run_etl.sh
│   ├── gcp_bootstrap.sh         # BQ dataset + external table を idempotent 作成
│   └── deploy_orchestration.sh  # Workflow + Scheduler を idempotent デプロイ
├── terraform/                   # GCS / BQ / Artifact Registry / IAM
├── workflows/dbt_pipeline.yaml  # Cloud Workflows 定義
├── tests/                       # pytest
├── docker-compose.yml           # Phoenix
└── Dockerfile + cloudbuild.yaml # dbt 実行用 Cloud Run Job image
```

### 5.5 データフロー (1 リクエスト分)

1. アプリが `tracer.start_as_current_span("llm.call")` で span 開始 → **L3-a Phoenix** へ OTLP 送信
2. 同じ span 内で `analytics_logger.emit(event_type="llm_call", ...)` を呼ぶ → Pydantic 検証 → L2-g のリングバッファに append
3. 大きいコンテンツは **L2-f ContentRouter** が `data/payloads/...` (or GCS payloads/) に書き、`content_uri = file://...` (or `gs://...`) を event に詰める
4. 背景フラッシュ (もしくは明示 `flush()`) が **L3-b RotatingFileSink** を呼び、`data/raw/service_name=.../event_type=.../dt=.../hour=.../*.jsonl` に追記
5. **L4 LocalUploader / GCSUploader** が定期的に `raw/` → `uploaded/` を移動
6. **L5 dbt** が `data/uploaded/**/*.jsonl` (or BQ external table) を読み、raw → staging → marts をリビルド
7. 分析は **L6 DuckDB / BQ Console** で SQL、トレース UI は **L3-a Phoenix / Langfuse** を見る。`trace_id` で両者を突合

### 5.6 IAM / セキュリティ境界 (GCP)

コンポーネント単位の Service Account:

| SA | 権限 | 用途 |
|---|---|---|
| `sa-uploader` | `roles/storage.objectAdmin` on `{bucket}/raw/`, `{bucket}/payloads/` | アプリ / サイドカーからの GCS 書込 |
| `sa-loader` | `roles/storage.objectViewer` + `roles/bigquery.dataEditor` | Cloud Workflows の GCS → BQ Load |
| `sa-dbt` | `roles/bigquery.user` + `roles/bigquery.dataEditor` on staging/marts | dbt 実行 |
| `sa-langfuse` | `roles/cloudsql.client` + `roles/storage.objectAdmin` on Langfuse bucket | Langfuse Pod |
| `sa-alerter` | `roles/monitoring.viewer` + Pub/Sub publisher | アラート転送 |

**秘匿情報**: Langfuse の DB パスワード / Anthropic API Key などは Secret Manager、Pod は Workload Identity で SA を受け取り Secret Manager から読む。

**ネットワーク** (推奨): GKE は Private cluster + Cloud NAT、Langfuse UI は IAP 経由 SSO、BigQuery / GCS は VPC Service Controls。

### 5.7 信頼性

- **アプリ → サイドカー**: ローカル FS 経由 (メモリバッファ + ファイル) で同期呼出を軽く保つ
- **サイドカー → GCS**: `tenacity` の指数バックオフ (1→2→4→8→16 秒、最大 5 回) → 失敗時 `dead_letter/`
- **GCS → BQ**: Cloud Workflows のリトライ (step 単位) → 失敗時 Slack 通知
- **冪等性**: `event_id` (UUID v7) + `ingested_at` で重複検知。Load Job を 2 回投げても MERGE or 後段 dbt で排除
- **バッファ監視**: アプリ内バッファ滞留量を Cloud Monitoring の custom metric に出す

---

## 6. 開発フェーズ / Roadmap

### 6.1 Phase 一覧

| Phase | 内容 | 状態 | 主要 PR / 参照 |
|---|---|---|---|
| **Phase 1** | ローカル環境 (Phoenix + DuckDB + dbt-duckdb 雛形) | ✅ 完了 | PR #24 |
| **Phase 2** | OTel 計装ライブラリ + AnalyticsLogger | ✅ 完了 | PR #24 |
| **Phase 3** | JSONL スキーマ + コンテンツ格納戦略 | ✅ 完了 | PR #24 |
| **Phase 4** | dbt モデル (raw / staging / marts) | ✅ 完了 | PR #24 |
| **Phase 5** | GCP 環境 (GCS / BQ / Cloud Run Job / Workflows / IaC / Monitoring) | 🔶 大部分実装 | Step 1, 3-9 完了。Step 2 (Langfuse) / Step 10 (各エージェントのデプロイ反映) 残 |
| Phase 6 | 検索基盤 (BigQuery Search Index + Enrichment / Vector Search) | 📋 未着手 | — |
| Phase 7 | ダッシュボード (Metabase + Looker Studio) | 📋 未着手 | — |
| Phase 8 | アラート (Grafana Alert + Cloud Monitoring 拡充) | 📋 未着手 | — |
| Phase 9 | 継続評価・セマンティック検索 (LLM-as-a-Judge / Vector Search) | 📋 未着手 | — |

### 6.2 連携先エージェント (計装状況)

| エージェント | 計装内容 | PR |
|---|---|---|
| `stock-analysis-agent` | llm_call / tool_invocation / message | PR #26 |
| `lifeplanner-agent` | business_event / error_event / llm_call (Anthropic + Vertex) | PR #27 |
| `piyolog-analytics` | conversation_event / business_event / error_event | PR #34 |
| `hotcook-agent` | business_event | PR #31 |
| `tech-news-agent` | business_event (article_collected / article_curated / digest_delivered) | PR (本 PR にて) |
| `driving-license-bot` | business_event (Phase 1+ 計画) | 計画中 |
| `kanie-lab-agent` | 未着手 (フロントエンド込みのため別 PR で対応) | — |

### 6.3 ローカル → GCP 移行手順

| 手順 | 内容 | 状態 |
|---|---|---|
| 1 | GCP プロジェクト + Artifact Registry (+ 将来: VPC / GKE) を準備 | ✅ Artifact Registry は Terraform 管理 |
| 2 | Langfuse on GKE を Helm chart でデプロイ | 📋 未着手 |
| 3 | GCS バケット 3 種 + ライフサイクルルール | ✅ Terraform |
| 4 | BigQuery データセット + external table | ✅ Terraform + `gcp_bootstrap.sh` |
| 5 | `PayloadWriter` / `UploadTransport` の GCS 実装 | ✅ Phase 5 で実装済 |
| 6 | `dbt/profiles.yml` に `target: gcp` 追加 | ✅ cross-DB macros + adapter dispatch |
| 7 | Cloud Run Jobs のコンテナ image を build & push | ✅ `Dockerfile` + `cloudbuild.yaml` |
| 8 | Cloud Scheduler + Cloud Workflows を設定 | ✅ `workflows/dbt_pipeline.yaml` + `deploy_orchestration.sh` |
| 9 | Cloud Monitoring のアラートポリシー | ✅ `terraform/monitoring.tf` |
| 10 | アプリの `.env` を `ENV=gcp` に切替、デプロイ | 各 consumer 側で個別実施 |

**カットオーバー**: 両基盤を並走 (shadow mode) でデータ整合性を 1〜2 週間確認してから正式切替。

### 6.4 Phase 6+ の拡張余地

| Phase | 追加 GCP サービス | 用途 |
|---|---|---|
| Phase 6 検索 | BigQuery Search Index | 全文検索 |
| Phase 6 検索 | Vertex AI Vector Search / BQ VECTOR_SEARCH | セマンティック検索 |
| Phase 6 Enrichment | Cloud Run Jobs (Haiku) | content_summary / content_keywords の後段付与 |
| Phase 7 BI | Looker Studio / Metabase on GKE | ダッシュボード |
| Phase 8 アラート | Cloud Monitoring + Pub/Sub + PagerDuty | SLO ベース通知 |
| スケール拡大時 | Pub/Sub + Dataflow | 千件/秒超のストリーミング取込 |

---

## 7. 設計判断ログ (ADR-lite)

| 日付 | 判断 | 理由 | 詳細 |
|---|---|---|---|
| 2026-04 | event のソースは **構造化 Pydantic schema** (raw JSON ではない) | event_type 別に厳格な field 検証、BQ external table のスキーマと一致 | §4.1 |
| 2026-04 | ローカル backend は **JSONL → DuckDB → dbt-duckdb** | ファイルベースで PR 内検証容易、外部依存なし | §5.1 |
| 2026-04 | GCP backend は **Hive パーティション JSONL → BQ external table** | dbt-bigquery でスキーマ管理、コスト最適化 (external table はストレージ料金のみ) | §4.4 |
| 2026-04 | Sink は **Protocol で差替可能** (`RotatingFileSink` / `NoOpSink` / `MemorySink`) | テスト時に NoOpSink、緊急時に環境変数で OFF | §5.3 |
| 2026-04 | ContentRouter で **inline / URI 切替** (閾値 8KB) | 大容量 LLM レスポンスを GCS に逃がす、event 本体は軽量に | §5.4 / API §6.2 |
| 2026-04 | **`service_name` で Hive パーティション** + IAM 分離 | エージェント別の集計が容易、誤った全件クエリのコスト爆発を防ぐ | §4.3 / §5.6 |
| 2026-04 | OTel exporter は `OTEL_EXPORTER_OTLP_ENDPOINT` で **Phoenix (local) → Langfuse (GCP)** に切替 | OTLP 準拠で SaaS / 自前ホストどちらでも | API §6.3 |
| 2026-04 | **Discriminated Union**: `event_type` ごとの必須フィールドを Pydantic が emit 時点で強制 | スキーマドリフトの検知が早期化 | §4.1 |
| 2026-04 | **`sha256:<hex>` prefix 強制**: `content_hash` / `input_args_hash` 等は `sha256_prefixed()` で必ず整形 | クエリで raw / hash の判別が明示的 | `hashing.py` |
| 2026-04 | **`ingested_at` は dbt Staging 層で付与** | アプリ側では発行しない (発行/取込の遅延を staging で観測) | dbt staging |
| 2026-04 | ローカル擬似 GCS: `data/raw/ → uploaded/ → dead_letter/` の 3 段構成 | 将来 GCS Uploader に差し替え可能 | §5.3 |
| 2026-04 | 大きなコンテンツは `data/payloads/{service}/{dt}/{event_id}.{ext}` に退避 | 8KB 既定、`content_uri` で参照 | §5.4 |
| 2026-05 | dbt 実行は **Cloud Run Job + Workflows + Scheduler** (Cloud Composer 不採用) | コスト 1/10、cron だけで十分 | §5.2 |
| 2026-05 | Cloud Monitoring アラートは **Slack 通知** (Email でなく) | チームの運用慣習、PagerDuty は overkill | §5.2 / `monitoring.tf` |
| 2026-05 | dbt 文法差は **cross-DB マクロ** で吸収 (5 マクロ) | DuckDB ↔ BQ で SQL 共通化 | `dbt/macros/cross_db.sql` |

---

## 8. 運用

詳細手順は別ドキュメントに分離:

- **Quickstart / 主要 API / 環境変数**: [README §0-§3](../README.md)
- **GCP 切替 (env 駆動)**: [README §4 GCP backend セットアップ](../README.md#4-gcp-backend-セットアップ)
- **Terraform IaC**: [`../terraform/README.md`](../terraform/README.md)
- **オーケストレーション (Cloud Workflows + Scheduler)**: [README §5](../README.md#5-運用-デプロイ)

### 8.1 開発フロー上のコンポーネント

| フェーズ | 触るもの |
|---|---|
| 新しい event_type を追加 | `analytics_platform/observability/schemas.py` に `SomethingEvent` を足し `AnyEvent` に入れる + `dbt/models/staging/stg_something.sql` 追加 |
| 新しい KPI を追加 | `dbt/models/marts/mart_*.sql` 追加 + `marts/schema.yml` にテスト追加 |
| GCP へ移行 | §5.3 の 4 箇所 (L2-f / L3-b / L4 / L5) のみ差替 |
| 既存エージェント計装 | producer 側 (L1) で `setup_tracer()` + `AnalyticsLogger` を DI するだけ |

---

## 9. セキュリティ・プライバシー

### 9.1 データ分類

| 種類 | 例 | 取扱い |
|---|---|---|
| **PII** | LINE userId / 取引明細 / 子の名前 | consumer 側で sha256 hash 化、raw は emit 対象外 |
| **機密** | API キー / DB 認証情報 | Secret Manager (本番)、`.env` (dev、gitignore)、emit 対象外 |
| **集計可** | event 本体 (event_id / metrics / latency) | BQ marts で集計、IAM で利用側 SA に閲覧権限 |
| **大容量** | LLM レスポンス raw / 添付ファイル | ContentRouter が GCS payloads/ に逃がす、`content_uri` のみ event に含める |

### 9.2 認証・認可

- **アプリ → GCS**: Workload Identity Federation で SA を受け取る
- **dbt → BigQuery**: `sa-dbt` SA、`analytics_staging` / `analytics_marts` への dataEditor のみ
- **Langfuse UI**: IAP (将来)
- **BigQuery 利用者**: IAM で `analytics_marts` 閲覧者と `analytics_raw` 管理者を分離

### 9.3 既知のリスク・残課題

- `data/payloads/` の GCS lifecycle 30 日が短い場合、長期再現性のため拡張要検討
- Langfuse on GKE 未デプロイ (Phase 5 残)
- VPC Service Controls 未設定 (推奨レベル、未必須)

---

## 10. テスト戦略

| レイヤ | 対象 | 状態 |
|---|---|---|
| Unit | schemas / content / hashing / analytics_logger / sinks | `tests/` で 93 件 |
| Integration | dbt-duckdb の SQL 実行 + アサーション (`assert_cache_hit_ratio_bounds.sql`) | dbt test |
| dbt-bigquery 妥当性 | `dbt parse` で接続なしの SQL チェック | CI で `make dbt-parse-bq` |
| E2E | demo_emit → JSONL → DuckDB → dbt → SQL 結果まで | `make etl` |

合計 93+ tests PASS (2026-05 時点)。

CI: `.github/workflows/pr-tests.yml` の `test-analytics-platform` job で pytest + demo + dbt 一気通貫。

---

## 11. 関連ドキュメント

- [`../README.md`](../README.md) — Quickstart / 主要 API / 環境変数 / 運用手順
- [`../terraform/README.md`](../terraform/README.md) — Terraform IaC 詳細 (state / backend / drift / import)
- [`../../docs/PROPOSALS/`](../../docs/PROPOSALS/) — モノレポ共通の機能個別 ADR
- [モノレポ全体の設計テンプレート](../../docs/) — `SYSTEM_DESIGN_TEMPLATE.md` / `README_TEMPLATE.md` / `PROPOSALS/TEMPLATE.md`

---

## 12. 用語集

| 用語 | 意味 |
|---|---|
| service_name | 計装対象エージェント名。Hive パーティションキー (`stock-analysis-agent` / `lifeplanner-agent` 等) |
| event_id | event 1 件の UUID v7。OTel span_id と相関付け用 |
| event_type | event の種別。`business_event` / `llm_call` / `error_event` / `conversation_event` / `tool_invocation` / `message` / `span_event` の 7 種 |
| Sink | event の出力先抽象 (`RotatingFileSink` / `NoOpSink` / `MemorySink` 等) |
| ContentRouter | 大容量 payload を inline / URI で振り分けるレイヤー (`CONTENT_INLINE_THRESHOLD_BYTES`) |
| RotatingFileSink | JSONL を Hive パーティション (`service_name=X/event_type=Y/dt=YYYY-MM-DD/hour=HH/`) で書き分け、サイズ / 時刻で rotate |
| LocalUploader | rotated JSONL を `uploaded/` に move する周期ジョブ (`ANALYTICS_UPLOAD_INTERVAL_SECONDS`) |
| GCSTransport | `LocalUploader` の GCP backend。`ANALYTICS_STORAGE_BACKEND=gcs` で有効化 |
| GCSPayloadWriter | ContentRouter の GCP backend。大容量 payload を直接 GCS に書く |
| external table | BigQuery が GCS の JSONL を直接クエリする仕組み。`analytics_raw.agent_events_external` |
| dbt staging | 1 日分の external table を fileformat 変換 + 重複除去した中間テーブル (90 日保持) |
| dbt marts | 用途別の最終集計 (`mart_llm_call_daily` / `mart_error_rate_by_service` 等、永続) |
| Discriminated Union | Pydantic v2 の機能。`event_type` 値で `LlmCall` / `BusinessEvent` 等を自動振り分け |
| Workload Identity | GCP の SA を Pod / Cloud Run に紐付ける仕組み。Secret Manager 認証用 |
| dead_letter | upload に失敗した raw JSONL の退避先。再試行時の参照用、90 日 lifecycle |
