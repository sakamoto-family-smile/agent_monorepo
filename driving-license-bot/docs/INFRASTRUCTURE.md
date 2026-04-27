# GCP インフラ構成と各コンポーネントの役割

driving-license-bot を GCP 上で稼働させるための全コンポーネント一覧と、それぞれの役割・スペック・IAM・コスト目安を整理する。

> 設計の文脈は [DESIGN.md §4 コンポーネント構成](./DESIGN.md#4-コンポーネント構成gcp)、技術選定の根拠は [INFRA_DECISIONS.md](./INFRA_DECISIONS.md) を参照。

---

## 1. アーキテクチャ全体図

```
┌──────────────────────────────────────────────────────────────────────┐
│ ① 入口層                                                              │
│   LINE Platform                                                       │
│         │ Webhook (HTTPS)                                             │
│         ▼                                                             │
│   Cloud Load Balancer                                                 │
│         │                                                             │
│         ▼                                                             │
│   Cloud Run: line-bot-service          ← min-instance=1               │
│     ・署名検証 / Reply Message / Rich Menu / Flex Message              │
│     ・即時 200 OK 返却 + Cloud Tasks に enqueue                        │
└──────────┬──────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│ ② 非同期処理層                                                         │
│   Cloud Tasks (driving-license-bot-jobs)                             │
│         │                                                             │
│         ▼                                                             │
│   Cloud Run: agent-service              ← min-instance=0              │
│     ・Supervisor + Sub-agents (Claude Agent SDK)                      │
│     ・Question Generator / Fact Checker / Quality Reviewer / Tutor   │
│     ・MCP 呼び出しは security-platform/MCP Proxy 経由                  │
└──────────┬──────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│ ③ データ・LLM 層                                                       │
│                                                                       │
│   ┌─────────────────────────┐  ┌────────────────────────────────┐   │
│   │ Vertex AI               │  │ Storage / DB                   │   │
│   │  ├─ Claude (Tokyo)      │  │  ├─ Firestore (state)          │   │
│   │  ├─ Gemini (cross-check)│  │  ├─ Cloud SQL pgvector         │   │
│   │  ├─ text-embedding-004  │  │  │   (question-bank)           │   │
│   │  └─ Model Armor         │  │  ├─ BigQuery (analytics)       │   │
│   └─────────────────────────┘  │  └─ GCS (signs/PDF/snapshots)  │   │
│                                └────────────────────────────────┘   │
│                                                                       │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │ security-platform/MCP Proxy (port 8080)                       │  │
│   │  ・Rate limit / DLP / Tool pinning / Injection 検知            │  │
│   │  ・全 MCP 呼び出しが intercept される                          │  │
│   └──────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
           ▲
           │
┌──────────────────────────────────────────────────────────────────────┐
│ ④ バッチ・運用層                                                       │
│                                                                       │
│   Cloud Scheduler (月次 03:00 JST)                                    │
│         │                                                             │
│         ▼                                                             │
│   Cloud Workflows: law-update-pipeline                               │
│     ・e-Gov diff → 影響問題を needs_review にフラグ → 運営者通知       │
│                                                                       │
│   Cloud Scheduler (夜間)                                              │
│         │                                                             │
│         ▼                                                             │
│   Cloud Run Job: question-generation-batch                            │
│     ・draft → fact-check → quality-review → 人間レビュー待ち           │
│                                                                       │
│   Cloud Run: review-admin-ui (IAP 保護)                               │
│     ・運営者 1 人専用、approve / reject / edit                         │
└──────────────────────────────────────────────────────────────────────┘

────────────────────────────────────────────────────────────────────────
[既存基盤との連携]

analytics-platform   → GCS / BigQuery / Langfuse を共用（本プロジェクト独自に作らない）
security-platform    → MCP Proxy / CVE 監視 / LINE 通知 / CI Security を共用
```

---

## 2. コンポーネント一覧

### 2.1 サマリ表

| # | サービス | 名称 | 主な役割 | 規模 / min-inst | 月額目安 |
|---|---|---|---|---|---|
| 1 | Cloud Run | `line-bot-service` | LINE Webhook 受信・即時応答 | min=1, CPU 1 / Mem 512Mi | $5〜10 |
| 2 | Cloud Run | `agent-service` | Supervisor + Subagents（LLM 生成本体） | min=0, CPU 1 / Mem 1Gi | $1〜3 |
| 3 | Cloud Run | `review-admin-ui` | 運営者専用問題レビュー UI | min=0, CPU 0.5 / Mem 256Mi | <$1 |
| 4 | Cloud Run Job | `question-generation-batch` | 問題プールの夜間補充 | 起動時のみ、Mem 1Gi | 含む LLM コスト |
| 5 | Cloud Tasks | `driving-license-bot-jobs` | Webhook 非同期化キュー | - | 無料枠 |
| 6 | Cloud Scheduler | `law-update-monthly` / `batch-nightly` | バッチ起動 cron | 月数回 | <$1 |
| 7 | Cloud Workflows | `law-update-pipeline` | 法令改正パイプライン | 月 1 回 | <$1 |
| 8 | Vertex AI | Claude on Tokyo | 問題・解説生成、Tutor | as-needed | $10〜30 |
| 9 | Vertex AI | Gemini on Tokyo | Quality Reviewer cross-check | as-needed | $5〜10 |
| 10 | Vertex AI | Model Armor | LLM ガード（前段） | - | 含む 8/9 |
| 11 | Vertex AI | `text-embedding-004` | 問題 embedding 生成（768 次元） | as-needed | <$1 |
| 12 | Firestore | `(default)` database | セッション・進捗・索引 | low-latency | $0〜数 $ |
| 13 | Cloud SQL Postgres | `question-bank` | 問題プール + pgvector 重複検査 | db-f1-micro | $10〜15 |
| 14 | BigQuery | `analytics_*` dataset | イベントログ・分析（共用） | 月 10GB 以下 | 無料枠 |
| 15 | GCS | `${project}-analytics-raw` | analytics-platform 共用 JSONL | 数 GB | 数 $ |
| 16 | GCS | `${project}-driving-license-bot` | 標識 SVG / PDF / 法令 snapshot | 数 GB | 数 $ |
| 17 | Secret Manager | `driving-license-bot-*` | LINE secrets / DB password | - | 無料枠 |
| 18 | Cloud Logging | デフォルト | アプリログ集約 | - | 無料枠 |
| 19 | Cloud Monitoring | デフォルト + custom metrics | レイテンシ・エラー率・コスト | - | 無料枠 |
| 20 | Artifact Registry | `driving-license-bot` repo | Cloud Run / Job 用 image | <1GB | <$1 |
| 21 | IAP | `review-admin-ui` 前段 | 運営者 Google アカウント認証 | - | 無料枠 |
| | | | | **合計** | **$35〜75 / 月** |

---

## 3. コンポーネント別の詳細

### 3.1 Cloud Run: `line-bot-service`

| 項目 | 内容 |
|---|---|
| 役割 | LINE Webhook を受信し、署名検証後に即時 200 OK を返す。実処理は Cloud Tasks に enqueue して非同期化する |
| なぜ min=1 か | LINE Webhook のタイムアウト要件と UX 上、コールドスタートの 5〜10 秒遅延が許容できないため |
| スペック | CPU 1 / Mem 512Mi、リクエスト同時実行 80 |
| エンドポイント | `POST /webhook` (公開), `GET /healthz` |
| 主な依存 | Firestore（セッション）、Cloud Tasks（enqueue）、Secret Manager（LINE secrets） |
| 主要ライブラリ | FastAPI, line-bot-sdk, analytics-platform |
| Service Account | `sa-line-bot` |
| 関連 env | `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN`, `CLOUD_TASKS_QUEUE`, `FIRESTORE_DATABASE` |
| Phase | Phase 1 で実装開始 |

### 3.2 Cloud Run: `agent-service`

| 項目 | 内容 |
|---|---|
| 役割 | Supervisor + Subagents（Question Generator / Fact Checker / Quality Reviewer / Tutor / Analytics）を動かす本体。Vertex AI Claude / Gemini を呼ぶ |
| min=0 の理由 | 非同期で呼ばれるため、起動遅延（数秒）は許容 |
| スペック | CPU 1 / Mem 1Gi、リクエスト同時実行 4（LLM 呼び出しのため低め） |
| エンドポイント | 内部のみ（Cloud Tasks worker / batch から呼ばれる） |
| 主な依存 | Vertex AI（Claude / Gemini / Embedding）、Cloud SQL（pgvector）、Firestore、GCS、MCP Proxy |
| 主要ライブラリ | claude-agent-sdk (Vertex モード), google-cloud-aiplatform, analytics-platform |
| Service Account | `sa-agent` |
| 関連 env | `ANTHROPIC_VERTEX_PROJECT_ID`, `CLOUD_ML_REGION=asia-northeast1`, `VERTEX_CLAUDE_MODEL`, `SECURITY_MCP_PROXY_URL` |
| Phase | Phase 2 で実装開始 |

### 3.3 Cloud Run: `review-admin-ui`

| 項目 | 内容 |
|---|---|
| 役割 | 運営者 1 人専用の問題レビュー UI。生成された問題の approve / reject / edit、reject 理由のタグ付け |
| 認証 | IAP（Identity-Aware Proxy）で運営者の Google アカウントのみ許可 |
| スペック | CPU 0.5 / Mem 256Mi |
| 主な依存 | Firestore（読書）、Cloud SQL（read-only） |
| Service Account | `sa-admin-ui` |
| 関連 env | `REVIEW_ADMIN_ALLOWED_EMAILS` |
| Phase | Phase 3 で実装開始（人間レビューがボトルネックになる前に最低限の UI を準備） |

### 3.4 Cloud Run Job: `question-generation-batch`

| 項目 | 内容 |
|---|---|
| 役割 | 夜間バッチで問題プールを補充。draft → fact-check → quality-review → 人間レビュー待ち（needs_review）→ 運営者承認後に published |
| 起動 | Cloud Scheduler から Cloud Workflows 経由で起動 |
| スペック | Mem 1Gi、Job timeout 30 分、max-retries 2 |
| 主な依存 | Vertex AI（Claude / Gemini）、Cloud SQL pgvector（重複検査）、Firestore（プール状態）、GCS |
| Service Account | `sa-batch` |
| 関連 env | `GENERATION_BATCH_SIZE`, `QUESTION_POOL_TARGET_SIZE`, `QUESTION_POOL_MIN_SIZE` |
| Phase | Phase 2 で実装開始 |

### 3.5 Cloud Tasks: `driving-license-bot-jobs`

| 項目 | 内容 |
|---|---|
| 役割 | LINE Webhook の非同期化キュー。`line-bot-service` が enqueue → worker が consume |
| 設定 | max-dispatches/sec=10, max-attempts=3, retry exponential backoff |
| Service Account | `sa-line-bot` (enqueue), worker SA (consume) |
| 関連 env | `CLOUD_TASKS_QUEUE`, `CLOUD_TASKS_LOCATION=asia-northeast1`, `CLOUD_TASKS_INVOKER_SA` |

### 3.6 Cloud Scheduler

| ジョブ名 | スケジュール | トリガー先 |
|---|---|---|
| `law-update-monthly` | `0 18 1 * *` (毎月 1 日 03:00 JST) | Cloud Workflows: `law-update-pipeline` |
| `batch-nightly` | `0 17 * * *` (毎日 02:00 JST) | Cloud Run Job: `question-generation-batch` |

### 3.7 Cloud Workflows: `law-update-pipeline`

| 項目 | 内容 |
|---|---|
| 役割 | e-Gov API → 法令 snapshot 取得 → 前回 snapshot と diff → 変更条文に紐づく問題を `needs_review` にフラグ → 運営者に LINE 通知 |
| 構造 | 5 ステップ（取得 / diff / 抽出 / フラグ / 通知）。各ステップは retry 3 回 |
| 失敗時 | Cloud Monitoring がアラート → 運営者に email + LINE 通知 |
| Service Account | `sa-workflow` |

### 3.8 Vertex AI: Claude (`asia-northeast1`)

| 項目 | 内容 |
|---|---|
| 役割 | 問題生成（Question Generator）、解説生成（Tutor）、Fact Checker のメイン LLM |
| モデル | Claude Opus 4.7 (高品質生成) / Haiku 4.5 (簡易解説) |
| リージョン | `asia-northeast1`（Tokyo フル対応、Phase 0 確定） |
| Prompt Caching | 法令本文・教則本文・スキル定義を `cache_control` で固定 |
| ガード | Vertex AI Model Armor が前段でプロンプトインジェクション・PII を検知 |
| Service Account | `sa-agent` / `sa-batch` に `roles/aiplatform.user` |
| 関連 env | `ANTHROPIC_VERTEX_PROJECT_ID`, `CLOUD_ML_REGION=asia-northeast1`, `VERTEX_CLAUDE_MODEL` |

### 3.9 Vertex AI: Gemini (`asia-northeast1`)

| 項目 | 内容 |
|---|---|
| 役割 | Quality Reviewer の cross-check（Claude と別系列モデルで判定が割れた問題を検出） |
| モデル | Gemini 2.5 Pro |
| 関連 env | `VERTEX_GEMINI_MODEL` |

### 3.10 Vertex AI: `text-embedding-004`

| 項目 | 内容 |
|---|---|
| 役割 | 問題本文の embedding 生成（768 次元）。Cloud SQL pgvector で重複・類似度検査に使用 |
| 関連 env | `EMBEDDING_MODEL=text-embedding-004`, `EMBEDDING_DIM=768` |

### 3.11 Firestore（`(default)` database, asia-northeast1）

| 項目 | 内容 |
|---|---|
| 役割 | セッション状態、ユーザープロフィール、進捗、LINE User ID 索引 |
| データモデル | [DESIGN.md §8.2](./DESIGN.md#82-firestore-データモデル) 参照 |
| アクセス | low-latency 読書（出題時の即時応答に必要） |
| Service Account | `sa-line-bot` (RW), `sa-agent` (RW), `sa-batch` (限定 W), `sa-admin-ui` (RW) |
| 想定規模 | 1 日 50k read / 5k write 以下で無料枠内 |

### 3.12 Cloud SQL for PostgreSQL: `question-bank`

| 項目 | 内容 |
|---|---|
| 役割 | 問題プール（メタデータ + 本文 hash + embedding）、pgvector による重複・類似度検査 |
| Tier | db-f1-micro（10GB SSD） |
| リージョン | `asia-northeast1` |
| 拡張 | pgvector |
| スキーマ概要 | `questions(question_id PK, version, status, embedding vector(768), body_hash, ...)` + `INDEX USING ivfflat` |
| Service Account | `sa-agent` (RW), `sa-batch` (RW), `sa-admin-ui` (RO views) |
| 関連 env | `CLOUDSQL_INSTANCE_CONNECTION_NAME`, `CLOUDSQL_DB`, `CLOUDSQL_USER`, `CLOUDSQL_PASSWORD_SECRET` |

### 3.13 BigQuery（既存 analytics_* dataset を共用）

| 項目 | 内容 |
|---|---|
| 役割 | 出題履歴・回答ログ・KPI 分析（[INTEGRATIONS.md analytics-platform](./INTEGRATIONS.md#analytics-platform) 参照） |
| Dataset | `analytics_raw` / `analytics_staging` / `analytics_marts`（**新規作成不要、既存共用**） |
| service_name フィルタ | `driving-license-bot-line` / `-agent` / `-batch` / `-admin` |
| 想定 mart | `mart_quiz_metrics`, `mart_question_quality`, `mart_user_engagement`, `mart_generation_health`, `mart_cross_check_disagreement` |
| Service Account | `sa-agent` / `sa-batch` (write via JSONL → GCS → external table) |

### 3.14 GCS

#### 14a. `${project}-analytics-raw`（既存共用）

| 項目 | 内容 |
|---|---|
| 役割 | analytics-platform の Hive partition JSONL（業務イベント・LLM 呼び出しログ） |
| パス | `service_name=driving-license-bot-*/event_type=*/dt=*/hour=*/*.jsonl` |

#### 14b. `${project}-driving-license-bot`（本プロジェクト専用）

| パス | 用途 |
|---|---|
| `signs/` | 道路標識 SVG / PNG（Wikimedia Commons PD + 自作） |
| `kyousoku/` | 警察庁「交通の方法に関する教則」PDF と構造化 JSON |
| `law-snapshots/YYYY-MM/` | e-Gov 法令 XML の月次 snapshot |
| `payloads/` | LLM 入出力の大容量ペイロード（analytics-platform の content router 経由） |

ライフサイクル: standard 30 日 → nearline 90 日 → coldline 1 年 → 削除（snapshot は archive 永続化）

### 3.15 Secret Manager

| Secret | 用途 |
|---|---|
| `driving-license-bot-line-channel-secret` | LINE 署名検証 |
| `driving-license-bot-line-channel-access-token` | LINE Push / Reply Message 送信 |
| `driving-license-bot-line-login-channel-secret` | LINE Login（Phase 2+） |
| `driving-license-bot-operator-line-user-ids` | 運営者宛通知用の LINE User ID |
| `driving-license-bot-cloudsql-password` | Cloud SQL pgvector 接続パスワード |

すべて Workload Identity 経由で SA に accessor 権限を付与。

### 3.16 Cloud Logging

| 項目 | 内容 |
|---|---|
| 役割 | 全 Cloud Run / Job のアプリログ集約。OpenTelemetry の trace_id で analytics-platform と突合可能 |
| 保持 | 30 日（既定） |

### 3.17 Cloud Monitoring

| メトリクス | 用途 |
|---|---|
| `run.googleapis.com/request_latencies` | line-bot-service の Webhook 応答レイテンシ |
| `cloudtasks.googleapis.com/queue/depth` | キュー滞留検知 |
| `workflowexecutions.googleapis.com/finished_execution_count` | law-update-pipeline 失敗検知 |
| カスタム: `question_pool_size` | プール枯渇アラート |
| カスタム: `human_review_backlog` | レビュー待ち滞留アラート |

### 3.18 Artifact Registry: `driving-license-bot`

| 項目 | 内容 |
|---|---|
| 役割 | Cloud Run / Cloud Run Job の Docker image 格納 |
| リージョン | `asia-northeast1` |
| 命名 | `asia-northeast1-docker.pkg.dev/${PROJECT}/driving-license-bot/<service>:<tag>` |

### 3.19 IAP（Identity-Aware Proxy）

| 項目 | 内容 |
|---|---|
| 役割 | `review-admin-ui` を運営者の Google アカウントのみに公開 |
| 設定 | `REVIEW_ADMIN_ALLOWED_EMAILS` に列挙したメールアドレスを `roles/iap.httpsResourceAccessor` で許可 |

---

## 4. Service Account 一覧

| SA | 紐付き先 | 主な権限 |
|---|---|---|
| `sa-line-bot` | `line-bot-service` | Firestore RW、Cloud Tasks enqueue、Secret Manager（LINE secrets）read |
| `sa-agent` | `agent-service` | `roles/aiplatform.user`、Firestore RW、BigQuery RW、Cloud SQL client、GCS RW、Secret Manager read |
| `sa-batch` | `question-generation-batch` Job | `roles/aiplatform.user`、Cloud SQL client、GCS RW、Firestore RW |
| `sa-admin-ui` | `review-admin-ui` | Firestore RW、Cloud SQL client（read-only） |
| `sa-workflow` | `law-update-pipeline` | Cloud Run Jobs invoker、GCS RW、Firestore RW |
| `sa-scheduler` | `law-update-monthly` / `batch-nightly` | Workflows invoker、Cloud Run Jobs invoker |
| `sa-cloudtasks-invoker` | Cloud Tasks → worker | Cloud Run invoker（worker エンドポイントへ） |

すべて **Workload Identity** で Cloud Run / Job に紐付け、API キーは持たない。Secret Manager は accessor 権限のみで read-only。

---

## 5. ネットワーク

### Phase 1〜2

- VPC: default を使用、Cloud Run はパブリックエンドポイント
- LINE 署名検証で実質的なアクセス制御
- security-platform/MCP Proxy は同一 VPC 内の private service として配置

### Phase 3+ 検討

- VPC Connector で内部 MCP / Cloud SQL を **private IP 化**
- IAP で `review-admin-ui` を保護（Phase 3 で実装）
- VPC Service Controls で BigQuery / GCS / Secret Manager のプロジェクト境界保護

---

## 6. リージョン戦略

| リソース | リージョン | 理由 |
|---|---|---|
| Cloud Run / Job / Tasks / Scheduler | `asia-northeast1` | 国内ユーザー最適化 |
| Firestore | `asia-northeast1` | low-latency 読書 |
| Cloud SQL | `asia-northeast1` | agent-service と同一リージョン |
| GCS（本プロジェクト専用） | `asia-northeast1` | 同上 |
| Vertex AI Claude / Gemini | `asia-northeast1` | Phase 0 で Tokyo フル対応を確認 |
| BigQuery | `US` | analytics-platform 既存運用と整合 |
| Artifact Registry | `asia-northeast1` | Cloud Run pull の低レイテンシ |

---

## 7. デプロイ単位とリソース命名規則

### Terraform（将来）

`piyolog-analytics` / `analytics-platform` と同パターンで以下を Terraform 管理予定（Phase 3+）:

- GCS バケット
- Cloud SQL インスタンス
- BigQuery dataset（既存共用なので追加不要）
- Service Account + IAM binding
- Secret Manager secret 枠（値は手動投入）
- Cloud Monitoring alert policies

頻繁に更新する Cloud Run / Workflows / Scheduler は shell script + Cloud Build で運用。

### 命名規則

| リソース種別 | パターン | 例 |
|---|---|---|
| Cloud Run service | `<purpose>` | `line-bot-service` |
| Cloud Run job | `<purpose>` | `question-generation-batch` |
| Cloud Tasks queue | `driving-license-bot-<purpose>` | `driving-license-bot-jobs` |
| Cloud Scheduler | `driving-license-bot-<purpose>-<freq>` | `driving-license-bot-law-update-monthly` |
| Cloud Workflows | `<purpose>-pipeline` | `law-update-pipeline` |
| GCS バケット | `${project}-driving-license-bot[-<purpose>]` | `myproj-driving-license-bot` |
| Cloud SQL instance | `driving-license-bot-<purpose>` | `driving-license-bot-question-bank` |
| Service Account | `sa-<purpose>` | `sa-line-bot` |
| Secret Manager | `driving-license-bot-<purpose>` | `driving-license-bot-line-channel-secret` |
| Artifact Registry | `driving-license-bot` | `asia-northeast1-docker.pkg.dev/...` |

---

## 8. Phase ごとのリソース増分

| Phase | 追加されるリソース |
|---|---|
| 1 | Cloud Run (line-bot-service)、Firestore、Secret Manager、Cloud Tasks、Artifact Registry、`sa-line-bot` |
| 2 | Cloud Run (agent-service)、Cloud Run Job (batch)、Cloud SQL、Vertex AI Claude/Gemini/embedding、Model Armor、`sa-agent` / `sa-batch`、本プロジェクト専用 GCS |
| 3 | Cloud Run (review-admin-ui)、IAP、`sa-admin-ui`、Cloud Monitoring custom metrics |
| 4 | Cloud Workflows、Cloud Scheduler、`sa-workflow` / `sa-scheduler`、law-update / batch-nightly cron |
| 5 | （模擬試験用 Firestore TTL 設定、Push Message リマインダー） |

---

## 9. 既存基盤との関係

- **analytics-platform**: GCS バケット（`${project}-analytics-raw`）・BigQuery dataset・Langfuse（将来）を**共用**。本プロジェクト独自リソースとして追加作成しない。詳細は [INTEGRATIONS.md](./INTEGRATIONS.md#analytics-platform)
- **security-platform**: MCP Proxy・CVE 監視・LINE 通知・CI Security を**共用**。本プロジェクトは inventory.yaml / scan.yaml に登録済（PR #53 でマージ済）。詳細は [INTEGRATIONS.md](./INTEGRATIONS.md#security-platform)

---

## 10. 月額コスト試算（再掲）

| 項目 | 月額目安 |
|---|---|
| Cloud Run min=1（line-bot-service） | $5〜10 |
| Cloud Run その他（min=0） | $1〜5 |
| Cloud SQL pgvector（db-f1-micro） | $10〜15 |
| Cloud Tasks | 無料枠 |
| Firestore | $0〜数 $ |
| BigQuery | 無料枠 |
| GCS | 数 $ |
| Vertex AI Claude（夜間バッチ） | $10〜30 |
| Vertex AI Gemini（cross-check） | $5〜10 |
| **合計** | **$35〜75 / 月** |

ターゲット: **月額 $40〜70 で運用**。LINE Push Message は無料枠内（800/月以下）。
