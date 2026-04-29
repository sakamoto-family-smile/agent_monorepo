# GCP インフラ決定メモ（Phase 0 確定）

GCP / Vertex AI / 周辺サービスに関する Phase 0 で確定する技術選定メモ。
設計上の位置付けは [DESIGN.md §4](./DESIGN.md#4-コンポーネント構成gcp) を参照。

---

## 1. Vertex AI Claude のリージョン（**確定: asia-northeast1**）

### 確認結果

[Vertex AI ドキュメント Locations](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations) で確認:

- Anthropic Claude on Vertex AI は **asia-northeast1（Tokyo）でフル対応**
- Claude Opus 4.7 / Sonnet 4.6 / Haiku 4.5 すべて Tokyo で利用可能
- グローバルエンドポイント（`location: global`）も GA 提供開始済（[Google Cloud Blog](https://cloud.google.com/blog/products/ai-machine-learning/global-endpoint-for-claude-models-generally-available-on-vertex-ai)）

### 採用方針

| 用途 | リージョン |
|---|---|
| 日常運用（問題生成・解説生成） | **`asia-northeast1`** |
| 障害時のフェイルオーバー | グローバルエンドポイント（`global`）を予備として保持 |
| 最新モデル先行検証 | `us-east5`（必要時のみスポット利用） |

### データ所在地に関する重要な注意

> Vertex AI ドキュメントによると「Endpoints don't guarantee data residency or in-region ML processing」。
> エンドポイントのリージョンは**データ所在地を保証するものではない**。データ所在地が必要な場合は別途データレジデンシードキュメントを参照すること。

学科試験 Bot は LINE User ID と回答ログのみが LLM に渡る設計（PII は最小化）であり、データ所在地の厳密な保証は不要と判断。プライバシーポリシーには Vertex AI 経由で送信する旨を明示済み（[PRIVACY_POLICY.md §3.1](./POLICIES/PRIVACY_POLICY.md#31-業務委託先クラウドサービス)）。

### env への反映

[`.env.example`](../.env.example) で以下を確定:

```bash
CLOUD_ML_REGION=asia-northeast1
```

### 残 TODO

- [ ] Tokyo リージョンでの prompt caching 対応の最終確認（[VERTEX_ENABLEMENT.md §1.3](./VERTEX_ENABLEMENT.md#13-prompt-caching-の確認) で `make vertex-verify` を 2 回実行 → `cache_read_input_tokens > 0` を確認）
- [ ] Model Armor の Tokyo リージョン対応確認（Phase 5+ 本番化検討時、当面 Anthropic builtin で代替）

---

## 2. 重複検査用ベクトル DB（**確定: Cloud SQL Postgres + pgvector**）

問題プールの重複・類似度検査用（[DESIGN.md §3.3](./DESIGN.md#33-mcp-サーバー) の `question-bank-mcp` の中核）。

### 比較結果

| 候補 | 月額目安 | スケール | 採用判定 |
|---|---|---|---|
| **Cloud SQL Postgres + pgvector**（db-f1-micro） | **$10〜15** | 〜数千 vector | ✅ **採用** |
| AlloyDB Omni (pgvector) | $50+ | 中〜大 | ❌ 過剰 |
| Vertex AI Vector Search | $40+（VM 常時稼働） | 中〜大 | ❌ 過剰 |
| Firestore Vector Search | 既存利用に寄せれば $0+ | 小〜中 | △ 機能制約あり |

### 採用理由

- 想定データ規模: **問題プール 200〜2000 件**（Phase 5 まで）
- Cloud SQL pgvector は db-f1-micro で月 $10〜15 程度（[Cloud SQL pricing](https://cloud.google.com/sql/pricing)）
- Vertex AI Vector Search は VM 常時稼働で最低 $40〜
- Firestore Vector Search は機能制約があり、また Firestore は既にセッション管理用途で使うため責務分離の観点でも別 DB が望ましい

### 構成

```
Cloud SQL for PostgreSQL
  - Tier: db-f1-micro
  - Storage: 10 GB SSD
  - Region: asia-northeast1
  - Extension: pgvector
  - Schema:
      questions (
        question_id TEXT PRIMARY KEY,
        embedding vector(768),
        body_hash TEXT,
        ...
      )
      INDEX ON questions USING ivfflat (embedding vector_cosine_ops)
```

### エンベディングモデル

- Vertex AI `text-embedding-004`（768 次元）
- 問題本文の生成直後に embedding を計算、Cloud SQL に挿入
- 重複検査は cosine similarity > 0.85 で類似判定

### 注意

- db-f1-micro は SLA 対象外（個人利用なので許容）
- Phase 6 以降で問題数が 1 万件を超える想定があれば db-g1-small / 標準マシンタイプへの引上げを検討

### 残 TODO

- [ ] db-f1-micro の月額実コスト測定（Phase 1 で実機確認）

---

## 3. Langfuse の運用形態

`analytics-platform` 側の方針に合わせる。analytics-platform の現状（README §3.1 / §3.7）：

- **未着手** — Langfuse on GKE（Cloud SQL + ClickHouse on GKE + Memorystore Redis + GCS）が想定
- ローカルでは Phoenix（Docker）で代替

### 本プロジェクトの方針

- **Phase 1〜2**: ローカル Phoenix 運用、本番は Cloud Logging + BigQuery のみで凌ぐ
- **Phase 3+**: analytics-platform 側で Langfuse on GKE が稼働し始めた時点で OTel Exporter のエンドポイントを切替
- 本プロジェクト独自に Langfuse を立てることはしない（analytics-platform 側に依存）

### 残 TODO

- [ ] analytics-platform 側 Langfuse 構築の方針・時期を確認

---

## 4. Cloud Run の min-instance 戦略

| サービス | min-instance | 理由 |
|---|---|---|
| `line-bot-service` | **1** | LINE Webhook の即時 200 OK 要件、コールドスタートで UX 著しく劣化 |
| `agent-service` | 0 | 非同期で呼ばれるため数秒の起動遅延は許容 |
| `review-admin-ui` | 0 | 運営者専用、頻度低 |
| 各 MCP service | 0 | バッチ・非同期コンテキストで呼ばれる |
| `question-generation-batch` (Job) | N/A | Cloud Run Job は実行時起動 |

### コスト試算（Phase 0 確定見積）

| 項目 | 月額目安 |
|---|---|
| Cloud Run min=1（line-bot-service、CPU 1 / Mem 512Mi 常時） | 約 $5〜10 |
| Cloud Run その他（min=0、想定リクエスト時間合計） | $1〜5 |
| Cloud SQL pgvector（db-f1-micro） | $10〜15 |
| Cloud Tasks | 無料枠内 |
| Firestore | 1 日 50k read / 5k write 想定で無料枠内〜数 $ |
| BigQuery | 月 10 GB スキャン以下で無料枠内 |
| GCS | 数 GB で月数 $ |
| Vertex AI Claude（夜間バッチ） | $10〜30 |
| Vertex AI Gemini（cross-check） | $5〜10 |
| **合計目安** | **$35〜75 / 月** |

ターゲット: 月額 $40〜70 で運用。LINE Push Message は無料枠内（800/月以下）。

### 残 TODO

- [ ] line-bot-service min=1 の実コスト測定（Phase 1 で実機確認）
- [ ] Cloud Run の Always-CPU と On-CPU の使い分け（コスト差）

---

## 5. Secret Manager の階層

```
projects/{project}/secrets/
  ├─ driving-license-bot-line-channel-secret/versions/latest
  ├─ driving-license-bot-line-channel-access-token/versions/latest
  ├─ driving-license-bot-line-login-channel-secret/versions/latest   # Phase 2+
  └─ driving-license-bot-operator-line-user-ids/versions/latest
```

- secret 名のセパレータは GCP の制約で `-` を使用（`/` は使えない）
- Anthropic / Google Cloud のクレデンシャルは Workload Identity 経由で SA に付与（Secret Manager 不要）
- アクセス制御: 各 Cloud Run service の SA に必要 secret のみ accessor 権限を付与

### 残 TODO

- [ ] Secret rotation 方針（LINE Channel Access Token は long-lived だが、定期 rotation する場合の手順）

---

## 6. ネットワーク（Phase 1 シンプル運用、Phase 3+ で見直し）

### Phase 1〜2

- VPC は default を使用、Cloud Run はパブリックエンドポイント
- LINE Webhook の署名検証で実質的なアクセス制御
- security-platform/MCP Proxy はコンテナ内 localhost、または同一 VPC 内の private service

### Phase 3+ 検討

- Cloud Run の VPC Connector → 内部 MCP / Cloud SQL を private IP 化
- IAP で review-admin-ui を保護
- VPC Service Controls による BigQuery / GCS / Secret Manager のプロジェクト境界保護

---

## 7. Phase 0 確定事項のまとめ

| # | 項目 | 確定内容 |
|---|---|---|
| 1 | Vertex AI Claude リージョン | `asia-northeast1`（Tokyo） |
| 2 | 重複検査ベクトル DB | Cloud SQL Postgres + pgvector（db-f1-micro） |
| 3 | エンベディングモデル | Vertex AI `text-embedding-004`（768 次元） |
| 4 | Langfuse | analytics-platform 側に依存、Phase 3+ で連携 |
| 5 | line-bot-service min-instance | 1（コールドスタート回避） |
| 6 | その他 Cloud Run min-instance | 0 |
| 7 | 月額コスト目標 | **$40〜70 / 月** |
| 8 | Secret Manager 命名 | `driving-license-bot-<purpose>` |
| 9 | LINE Login プロバイダー | Phase 1 着手時に作成（複数 Bot 名寄せの将来準備） |
