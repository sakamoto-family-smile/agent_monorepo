# GCP インフラ決定メモ（Phase 0）

GCP / Vertex AI / 周辺サービスに関する Phase 0 で確定する技術選定メモ。
設計上の位置付けは [DESIGN.md §4](./DESIGN.md#4-コンポーネント構成gcp) を参照。

---

## 1. Vertex AI Claude のリージョン

### 候補

| リージョン | 採用案位置付け | 想定メリット | 想定デメリット |
|---|---|---|---|
| `asia-southeast1`（シンガポール） | **第一候補** | 日本からのレイテンシが比較的良好、Claude 提供実績あり | 物理的には asia-northeast1 より遠い |
| `asia-northeast1`（東京） | 採用できれば理想 | 国内ユーザー向け最適、データ所在国としても有利 | Claude on Vertex の提供有無を最新確認する必要あり |
| `us-east5`（バージニア） | 代替 | 最新モデル先行提供 | レイテンシ大、データ所在地の観点で不利 |

### 決定方針

1. **Phase 0 で `asia-northeast1` の Claude 提供状況を Vertex AI Model Garden で確認**
2. 提供されていれば `asia-northeast1` を採用（データ所在地的に最有利）
3. 提供されていなければ `asia-southeast1` を採用
4. `us-east5` は最新モデル先行検証用のみで本番採用しない

### 注意点

- `analytics-platform` の BigQuery location は既存運用と整合させる必要あり（既定: `US`）。Vertex リージョンとは別軸で評価。
- Anthropic Claude SDK の Vertex バックエンドは `ANTHROPIC_VERTEX_PROJECT_ID` と `CLOUD_ML_REGION` を環境変数で指定。

### 確認 TODO

- [ ] Vertex AI Model Garden での Claude モデル提供リージョン確認
- [ ] 採用リージョンでの prompt caching 対応確認
- [ ] Model Armor の対応リージョン確認（Vertex AI Claude と同じリージョン必須）

---

## 2. 重複検査用ベクトル DB

問題プールの重複・類似度検査用に必要（[DESIGN.md §3.3](./DESIGN.md#33-mcp-サーバー) の `question-bank-mcp` の中核）。

### 候補

| 候補 | 想定スケール | コスト感 | 運用負担 | 備考 |
|---|---|---|---|---|
| **Vertex AI Vector Search** | 小〜中 | インデックス保有時間で課金、待機コストあり | フルマネージド、Vertex の他コンポーネントとの統合容易 | 初期設定がやや複雑 |
| **AlloyDB pgvector** | 小〜大 | インスタンス常時稼働コスト | DB 知識があれば運用容易 | 既存運用と統合しやすい SQL |
| **Cloud SQL Postgres + pgvector** | 小 | AlloyDB より安価 | 同上 | スケール上限あり |
| **Firestore Vector Search** | 小 | 既存 Firestore に統合 | 学習コスト低 | 機能制限あり、用途次第 |

### 想定データ規模

- 問題プール: 数百〜数千件
- 各問題のベクトル: 1024〜1536 次元
- 類似度検索頻度: 生成時の重複チェック（バッチ）+ 出題時の関連問題抽出（オンライン）

### 決定方針

1. **Phase 0 ではコスト試算のみ実施**（実装は Phase 2）
2. 試算上の優先順位:
   - スケールが小さく Vector Search の常時インスタンスがコスト過大になる場合 → **Cloud SQL pgvector** または **Firestore Vector Search** を候補
   - Phase 2 着手時点で Phase 1 の実利用ログから規模を再評価して確定
3. analytics-platform は AlloyDB を導入していないため、analytics-platform との共有は考慮しない

### 確認 TODO

- [ ] Vertex AI Vector Search の月額試算（最小構成）
- [ ] Cloud SQL Postgres + pgvector の最小スペックでの月額試算
- [ ] Firestore Vector Search の機能制約確認（次元数上限・距離関数）
- [ ] エンベディングモデルの選定（Vertex AI `text-embedding-004` 等）

---

## 3. Langfuse の運用形態

`analytics-platform` 側の方針に合わせる。analytics-platform の現状（README §3.1 / §3.7）：

- **未着手** — Langfuse on GKE（Cloud SQL + ClickHouse on GKE + Memorystore Redis + GCS）が想定
- ローカルでは Phoenix（Docker）で代替

### 本プロジェクトの方針

- **Phase 1〜2**: ローカル Phoenix 運用、本番は Cloud Logging + BigQuery のみで凌ぐ
- **Phase 3+**: analytics-platform 側で Langfuse on GKE が稼働し始めた時点で OTel Exporter のエンドポイントを切替
- 本プロジェクト独自に Langfuse を立てることはしない（analytics-platform 側に依存）

### 確認 TODO

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

### コスト試算（Phase 0）

| 項目 | 月額目安 |
|---|---|
| Cloud Run min=1（line-bot-service、CPU 1 / Mem 512Mi 常時） | 約 $5〜10 |
| Cloud Run その他（min=0、想定リクエスト時間合計） | $1〜5 |
| Cloud Tasks | 無料枠内 |
| Firestore | 1 日 50k read / 5k write 想定で無料枠内〜数 $ |
| BigQuery | 月 10GB スキャン以下で無料枠内 |
| GCS | 数 GB で月数 $ |
| Vertex AI Claude（夜間バッチ） | $10〜30 |
| Vertex AI Gemini（cross-check） | $5〜10 |
| **合計目安** | **$25〜60 / 月** |

ターゲット: 月額 $30〜50 で運用。LINE Push Message は無料枠内（800/月以下）。

### 確認 TODO

- [ ] line-bot-service min=1 の実コスト測定（Phase 1 で実機確認）
- [ ] Cloud Run の Always-CPU と On-CPU の使い分け（コスト差）

---

## 5. Secret Manager の階層

```
projects/{project}/secrets/
  ├─ driving-license-bot/line-channel-secret/versions/latest
  ├─ driving-license-bot/line-channel-access-token/versions/latest
  ├─ driving-license-bot/line-login-channel-secret/versions/latest   # Phase 2+
  └─ driving-license-bot/operator-line-user-ids/versions/latest
```

- Anthropic / Google Cloud のクレデンシャルは Workload Identity 経由で SA に付与（Secret Manager 不要）
- アクセス制御: 各 Cloud Run service の SA に必要 secret のみ accessor 権限を付与

### 確認 TODO

- [ ] Secret 命名規則（プレフィクスやリネーム規則）の最終決定
- [ ] Secret rotation 方針（LINE Channel Access Token は long-lived だが、定期 rotation する場合の手順）

---

## 6. 各種オープン課題の集約

§1〜5 の TODO を [DESIGN.md §14.2 GCP / LLM 系](./DESIGN.md#142-gcp--llm-系) に反映する。
Phase 0 完了の判定: 各 §の TODO がすべて消化されている、または「Phase 1 着手まで未確定で OK」と判断されている状態。
