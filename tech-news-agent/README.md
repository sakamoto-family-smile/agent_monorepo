# tech-news-agent

データ基盤 (BigQuery / Snowflake / dbt / Iceberg / Databricks / データ品質 / データガバナンス 等) の最新ニュース・論文・トレンドを毎日 LINE で受け取るパーソナル情報配信サービス。LINE 上の自然言語質問 → 蓄積記事からの検索・要約回答もサポート。

将来的にセキュリティ / クラウド / LLM 動向など他ドメインに拡張できる汎用「技術ニュースエージェント」として設計。

**ステータス**: **Phase 1 MVP 実装完了**。RSS 5 ソース + arXiv を収集→LLM キュレーション→LINE Push まで動作。Phase 1.5 以降は設計書記載の通り未着手。

---

## 0. 位置付け

本エージェントは **モノレポ横断の分析基盤 `analytics-platform` の第一級クライアント** として構築する。収集した記事データは `analytics-platform` の Hive パーティション JSONL に書き、dbt で staging/marts に物理化、LINE bot も DuckDB read 経由で同じデータを参照する。

この設計により「分析対象のデータは分析基盤に格納する」という要件が自然に満たされ、dbt モデルを追加するだけでトレンド分析・配信統計・ソース別カバレッジが計算できるようになる。

---

## 1. 目的とスコープ

| 項目 | 内容 |
|---|---|
| 目的 | データ基盤領域のニュース・論文・トレンドを毎日 LINE で受信、LINE 上で蓄積記事からの質問応答 |
| 配信対象 | 自分専用 (1 ユーザ) |
| 配信頻度 | 日次 1 回 (JST 06:30 収集 → 07:00 配信) |
| 配信形式 | Flex Message (タイトル + 1-2 文要約 + タグ + 出典 URL)、Top 5-7 + arXiv 1-2 本 |
| 対話 | LINE 上でチャット質問 → 蓄積データから検索・回答 (Phase 2 以降) |
| 初期ドメイン | データ基盤 |
| 将来ドメイン | セキュリティ / クラウド / LLM 動向 (ドメイン設定ファイルで追加) |
| 実行環境 | **Phase 1-3 はローカル / Docker Compose**、Phase 4 で GCP 移行 |

### 設計原則

- **ローカル優先**: モノレポの `analytics-platform` 流儀に合わせ、Phase 1-3 は完全ローカルで閉じる
- **コスト最小**: LLM 以外の課金要素を排除。LLM も Haiku 4.5 中心 + prompt caching
- **データ資産化**: 収集データは JSONL → dbt → DuckDB の分析基盤に載せる
- **拡張性**: 新ドメインは `sources.yaml` にソース追加するだけで増やせる
- **エージェント駆動**: 要約・分類・重要度判定を LLM に委譲、ロジックを最小化

---

## 2. モノレポとの整合

### 2.1 採用基盤マッピング

| レイヤー | 本プロジェクト採用 | 根拠 |
|---|---|---|
| 記事ストレージ | **analytics-platform JSONL** (`data/raw/service_name=tech-news/event_type=article/...`) → dbt staging/marts | 「分析対象は分析基盤に」要件に直結 |
| 分析クエリ | **DuckDB** (read-only、`analytics.duckdb`) | ローカル高速、LINE QA のクエリも DuckDB 経由 |
| ベクトル検索 | **sqlite-vec** 併用テーブル (Phase 2) | DuckDB VSS も選択肢、Phase 2 で決定 |
| 観測性 | **analytics-platform** (OTel + JSONL → DuckDB) | `llm_call` / `business_event` / `error_event` を emit |
| LLM | **`llm-client/` 新設共通パッケージ** (`lifeplanner-agent/services/llm_client.py` を切り出し、tech-news 着手前に専用 PR で整備) | 重複実装回避、piyolog Phase 3 でも再利用 |
| LINE SDK | `stock-analysis-agent/services/line_client.py` パターン踏襲 + `ImageMessage` / Flex 拡張 | 既存資産 |
| スケジューラ | **Phase 1-3**: `cron` + Docker Compose / **Phase 4**: Cloud Scheduler → Cloud Run Job | ローカル dev 可能性維持 |
| 非同期処理 | **FastAPI BackgroundTasks** (Phase 1-3) / Pub/Sub (Phase 4+) | LINE 3 秒制約には BackgroundTasks で十分 |
| 会話状態 | **SQLite** (hot path)、必要に応じて analytics-platform にも emit | hotcook / piyolog 流儀 |
| MCP | 初期なし、Phase 2 以降で sqlite-vec MCP / GitHub MCP を検討 | オーバーエンジニアリング回避 |
| security-platform | `inventory.yaml` / `scan.yaml` に登録 | モノレポ規約 |

### 2.2 GCP 移行方針

`analytics-platform` の Phase 5+ (BigQuery / GCS / Langfuse on GKE) に便乗する。本プロジェクト単独で GCP 直行しない。移行時の差替点:

- JSONL → GCS raw バケット (変更なし、sink の root_dir だけ GCS URI)
- DuckDB → BigQuery (dbt profile を `bigquery` target に切替、SQL ほぼ共通)
- Vector: sqlite-vec → BigQuery `VECTOR_SEARCH`
- Embedding: local (sentence-transformers) → Vertex AI
- Scheduler: cron → Cloud Scheduler + Cloud Run Job
- LINE webhook: uvicorn → Cloud Run Service

---

## 3. 機能要件

### 3.1 Phase 1 (MVP)

| ID | 機能 | 説明 |
|---|---|---|
| F-01 | RSS 収集 | 主要 5 ソースから日次収集 |
| F-02 | arXiv 収集 | `cs.DB` / `cs.DC` / `cs.IR` の 3 カテゴリ、前日分、3 秒間隔で rate limit 遵守 (`cs.LG` は Phase 1.5 でキーワードフィルタ併用して追加) |
| F-03 | URL 正規化 + 重複排除 | UTM/fragment 除去、末尾スラッシュ正規化後にハッシュ → article_id に使用 |
| F-04 | 関連度スコアリング | Claude Haiku 4.5 で 0-10 点 (バッチ 10 件/プロンプト、prompt caching) |
| F-05 | 日本語要約 | Claude Haiku 4.5 で 1-2 文 |
| F-06 | タグ付け | `bigquery` / `dbt` / `iceberg` 等のタグ + ドメイン分類 |
| F-07 | ランキング | `final_score = llm_relevance_score (0-10) * source_weight` でスコア化、`RELEVANCE_THRESHOLD=5.0` 固定閾値で通過、Top 7 + arXiv 1-2 本 |
| F-08 | LINE 配信 | Flex Message (カルーセル最大 10 バブル) |
| F-09 | analytics-platform 出力 | raw/curated/digest を JSONL に emit、`business_event` で配信成否も記録 |
| F-10 | アクセス制御 | `LINE_USER_IDS` 許可リスト (自分 1 人) |

### 3.2 Phase 1.5

| ID | 機能 |
|---|---|
| F-11 | GitHub Trending / Releases watchlist |
| F-12 | Zenn / Qiita / はてブ RSS 追加 |
| F-13 | Reddit `r/dataengineering` 取込 |
| F-14 | プロンプトキャッシュの詳細チューニング |
| F-15 | 失敗ソースの週次レポート (Flex Message 風) |
| F-16 | arXiv `cs.LG` + キーワードフィルタ (`data pipeline` / `vector search` / `embedding` / `RAG` / `lakehouse` 等) 追加 |

### 3.3 Phase 2 (インタラクティブ QA)

| ID | 機能 |
|---|---|
| F-21 | LINE Webhook (`stock-analysis-agent` 流儀、署名検証 + 即 200) |
| F-22 | Embedding 生成 (Phase 2 着手時点の curated を一括、以降は incremental) |
| F-23 | sqlite-vec / duckdb-vss でベクトル検索 |
| F-24 | ハイブリッド検索 (ベクトル + キーワード BM25 風) |
| F-25 | QA Agent (Intent → Rewrite → Retrieve → Rerank → Answer) |
| F-26 | reply_token が有効な限り reply_message で無料返信、タイムアウト時のみ push |
| F-27 | `showLoadingAnimation` で最大 60 秒の検索中表示 |

### 3.4 Phase 3 以降

| ID | 機能 | Phase |
|---|---|---|
| F-31 | セキュリティドメイン追加 (OWASP / CVE / Snyk Blog) | 3 |
| F-32 | クラウドドメイン追加 (GCP/AWS/Azure アナウンス) | 3 |
| F-33 | LLM 動向ドメイン追加 (Anthropic/OpenAI/DeepMind) | 3 |
| F-34 | ドメイン別配信時間設定 | 3 |
| F-35 | 週次/月次ダイジェスト | 3 |
| F-36 | 配信 Flex Message の各記事バブルに 👍/👎 Postback ボタン | 3 |
| F-37 | フィードバック集計 → `sources.yaml` の source_weight を自動チューニング | 3 |
| F-38 | フィードバック反映の relevance_scorer prompt を動的更新 (tag 別好み学習) | 3 |
| F-39 | **動的閾値化**: 直近 14 日の 👍/👎 分布 + 配信数から percentile ベースで `RELEVANCE_THRESHOLD` を自動調整 | 3 |
| F-41 | GCP 移行 (analytics-platform Phase 5+ と合流) | 4 |
| F-51 | Firebase Auth + LIFF で複数ユーザ対応 | 5 |

---

## 4. データソース

### 4.1 Phase 1 初期ソース (主要 5 + arXiv)

| カテゴリ | ソース | 取得方法 | 備考 |
|---|---|---|---|
| 企業技術ブログ | Google Cloud Blog (Data Analytics) | RSS | `cloud.google.com/blog/products/data-analytics/rss` |
|   | AWS Big Data Blog | RSS |   |
|   | Databricks Blog | RSS |   |
|   | Snowflake Blog | RSS |   |
| 国内 | Zenn (topic: bigquery) | RSS | Phase 1 は 1 topic に絞る |
| 論文 | arXiv cs.DB / cs.DC / cs.IR | arXiv API | 公式 API、3 秒間隔 rate limit |

### 4.2 Phase 1.5 で追加

| ソース | 取得方法 |
|---|---|
| Netflix / Uber / Airbnb Engineering | RSS (Medium) |
| Zenn 他 topic (data-engineering / dbt 等) | RSS |
| Qiita (tag: BigQuery, dbt, Snowflake 等) | RSS/API |
| はてブ テクノロジー + キーワードフィルタ | RSS |
| GitHub Trending | HTML スクレイピング (requests + BeautifulSoup) |
| GitHub Releases (watchlist: dbt-core / Iceberg / Trino / DuckDB) | REST API |
| Reddit `r/dataengineering` | JSON API (無認証) |

### 4.3 配信枠配分 (1 日)

| トラック | 配信本数 | ソース |
|---|---|---|
| 技術ニュース | 5 本 | 企業ブログ + Zenn (+ Phase 1.5 以降: Qiita / はてブ / Reddit) |
| OSS 動向 | 1-2 本 | GitHub Trending / Releases (Phase 1.5 から) |
| 論文 (arXiv) | 1-2 本 | arXiv |
| **合計** | **7-9 本** |   |

### 4.4 ソース設定ファイル

```yaml
# config/sources.yaml (Phase 1 初期)
domain: data_platform
# priority → weight マッピング (Ranker で使用):
#   3 (★★★) = 一次情報・信頼度高 (公式ブログ等)  → weight 1.5
#   2 (★★)  = エンジニアリング品質中              → weight 1.0
#   1 (★)   = ノイズ混じり (SNS系・集約サイト)    → weight 0.7
sources:
  - name: google_cloud_data_analytics
    type: rss
    url: https://cloud.google.com/blog/products/data-analytics/rss
    priority: 3
  - name: aws_big_data
    type: rss
    url: https://aws.amazon.com/blogs/big-data/feed/
    priority: 3
  - name: databricks
    type: rss
    url: https://www.databricks.com/blog/feed
    priority: 3
  - name: snowflake
    type: rss
    url: https://www.snowflake.com/blog/feed/
    priority: 3
  - name: zenn_bigquery
    type: rss
    url: https://zenn.dev/topics/bigquery/feed
    priority: 2
  - name: arxiv
    type: arxiv
    categories: [cs.DB, cs.DC, cs.IR]       # Phase 1.5 で cs.LG + keyword 追加
    rate_limit_seconds: 3
    priority: 3                              # 論文は別トラックなのでランキング無関係、重み 1.0 固定扱い
```

**Ranker ロジック**:

```python
final_score = llm_relevance_score * source_weight  # llm: 0-10, weight: 0.7/1.0/1.5
# RELEVANCE_THRESHOLD 以上のみ配信候補に
# トラック別 Top N を選出 (技術ニュース 5 / OSS 1-2 / arXiv 1-2)
```

**閾値**: Phase 1 は `RELEVANCE_THRESHOLD=5.0` 固定 (環境変数で上書き可)。Phase 3 の F-39 で動的化。

ドメイン拡張時は `config/security.yaml`, `config/llm.yaml` 等を追加するだけ。

---

## 5. アーキテクチャ

### 5.1 Phase 1 (ローカル)

```
┌─────────────────────────────────────────────────────────┐
│ cron (06:30 JST) + docker compose                       │
└───────────────────┬─────────────────────────────────────┘
                    │ POST /internal/run-pipeline
                    ▼
┌─────────────────────────────────────────────────────────┐
│ FastAPI: tech-news-agent (port 8300)                    │
│                                                         │
│  POST /internal/run-pipeline (cron から叩く)            │
│   ├─ Collector: RSS / arXiv → JSONL emit                │
│   ├─ Curator: Dedup → Score → Summarize → Tag → Rank    │
│   │   (全て analytics-platform に emit)                 │
│   └─ Publisher: Flex Message → LINE Push                │
│                                                         │
│  POST /api/line/webhook  (Phase 2 から有効化)           │
│   ├─ TextMessage → QA Agent → reply/push                │
│   └─ 認証: X-Line-Signature                             │
│                                                         │
│  GET /healthz                                           │
└───────┬─────────────────────────────────┬───────────────┘
        │                                 │
        ▼                                 ▼
┌────────────────────────────┐  ┌─────────────────────────┐
│ analytics-platform         │  │ SQLite                  │
│  data/raw/                 │  │ conversations (Phase 2) │
│   service_name=tech-news/  │  │ user_state              │
│   event_type=article/...   │  └─────────────────────────┘
│  → dbt → analytics.duckdb  │
│     (raw_articles,         │
│      curated_articles,     │
│      article_embeddings)   │
└────────────────────────────┘
```

### 5.2 Phase 4 (GCP 移行後、将来)

```
┌──────────────────────────────┐
│ Cloud Scheduler (06:30 JST)  │
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│ Cloud Run Job: pipeline      │
│  Collector → Curator →       │
│  JSONL → GCS                 │
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│ GCS raw/uploaded/payloads    │
└──────────┬───────────────────┘
           ▼ Load Job
┌──────────────────────────────┐
│ BigQuery                     │
│  analytics_raw/staging/marts │
│  (dbt-bigquery)              │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│ Cloud Run Service: webhook   │
│  LINE + QA Agent             │
│  BigQuery VECTOR_SEARCH      │
└──────────────────────────────┘
```

---

## 6. エージェント構成

LangGraph は **Phase 2 の QA Agent から** 採用する。Phase 1 の収集・キュレーションは単純な関数チェーンで十分 (monorepo 流儀)。

| エージェント | 責務 | モデル | Phase |
|---|---|---|---|
| Collector | RSS / arXiv 取得 | 純 Python | 1 |
| URL Normalizer | UTM 除去・正規化 | 純 Python | 1 |
| Dedup | 過去 30 日と照合 | 純 Python (DuckDB 検索) | 1 |
| Relevance Scorer | Haiku 4.5、バッチ 10 件/プロンプト、system prompt に `cache_control` | Haiku 4.5 | 1 |
| Summarizer | 1-2 文要約 | Haiku 4.5 | 1 |
| Tagger | タグ + ドメイン分類 | Haiku 4.5 | 1 |
| Ranker | スコア + ソース重み、トラック別 Top N | ルールベース | 1 |
| Publisher | Flex Message 構築 + LINE Push | 純 Python (テンプレート) | 1 |
| Embedder | 記事 embedding 生成 | sentence-transformers (local) / Vertex AI (GCP) | 2 |
| QA Agent | Intent → Rewrite → Retrieve → Rerank → Answer | Haiku + Sonnet 混成 | 2 |

### 6.1 LLM コスト最適化

- **バッチスコアリング**: 10 件まとめて 1 プロンプト (× 4,500 件/月 ÷ 10 = 450 プロンプト)
- **prompt caching**: SYSTEM_PROMPT と few-shot 例に `cache_control=ephemeral` を付与 (`lifeplanner-agent/services/llm_client.py` の `cache_system=True` / `complete_messages` を使用)
- **モデル階層**: Haiku 4.5 既定、論文アブスト要約など複雑案件のみ Sonnet 4.6

想定コスト (月):
- スコアリング: Haiku 450 プロンプト ≒ $0.5
- 要約: 通過分 (仮に 30%) = 1,350 件 ≒ $1-2
- Phase 2 QA: 10 質問/日 × Haiku+Sonnet ≒ $1-2
- **合計: 月 $3-5**

---

## 7. データモデル

### 7.1 analytics-platform JSONL (primary)

既存 schema (`analytics_platform.observability.schemas.BusinessEvent`) の `business_event` を以下のように使う:

```json
{
  "event_type": "business_event",
  "business_domain": "tech_news",
  "action": "article_collected" | "article_curated" | "digest_delivered",
  "resource_type": "article" | "digest",
  "resource_id": "<article_id or digest_id>",
  "attributes": { ...ドメイン固有フィールド... }
}
```

**record の中に入れる attributes 例 (`article_collected`)**:

```json
{
  "source_type": "rss",
  "source_name": "google_cloud_data_analytics",
  "url": "https://...",
  "url_normalized": "https://...",
  "title": "...",
  "content_preview": "...",           // 最初 500 字
  "content_hash": "sha256:...",
  "author": "...",
  "published_at": "2026-04-24T...",
  "fetched_at": "2026-04-24T..."
}
```

大容量な本文は `content_uri` (`file://...` / GCP 時は `gs://...`) に外出し。

### 7.2 dbt staging/marts (DuckDB)

```
dbt/models/
├── staging/
│   ├── stg_tech_news_articles.sql    (business_event から article_collected を抽出)
│   ├── stg_tech_news_curations.sql   (article_curated)
│   └── stg_tech_news_digests.sql     (digest_delivered)
└── marts/
    ├── mart_articles_curated.sql     (scored + summarized 済み、QA 用)
    ├── mart_article_embeddings.sql   (Phase 2 から)
    └── mart_source_coverage.sql      (ソース別カバレッジの日次)
```

### 7.3 SQLite (hot path、Phase 2+)

```sql
-- 会話状態 (QA Agent 用)
CREATE TABLE sessions (line_user_id TEXT PRIMARY KEY, last_query_at TEXT);
CREATE TABLE qa_history (
  message_id TEXT PRIMARY KEY,
  line_user_id TEXT,
  query TEXT,
  answer TEXT,
  top_k_article_ids TEXT,   -- JSON array
  created_at TEXT,
  input_tokens INT,
  output_tokens INT,
  cache_read_tokens INT
);
```

### 7.4 article_id の決定論的生成

```python
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

def normalize_url(url: str) -> str:
    p = urlparse(url.strip())
    # UTM パラメータ・fragment 除去、ホスト小文字化、末尾スラッシュ正規化
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith('utm_')])
    path = p.path.rstrip('/') or '/'
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, '', query, ''))

def article_id(url: str) -> str:
    normalized = normalize_url(url)
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]
```

---

## 8. LINE 配信設計

### 8.1 Flex Message (Phase 1)

- **最大 10 バブルの carousel**: Top 7 + arXiv 1-2 本 = 8-9 バブルで収容
- バブル構成: タイトル / 1-2 文要約 / タグ / 出典表示 / 「詳しく読む」ボタン (元 URL)
- カラー: Paper Cream / Deep Ink / Peach 系 (既存エージェントの可視化方針に揃える)
- Phase 3 でフィードバックボタン (👍 / 👎) を同じバブルに追加 (§8.4 参照)

### 8.2 Phase 2 QA の Reply vs Push

LINE 料金は 2024 年以降改定され、個人 OA でも超過で課金。そのため:

| シナリオ | 返信方式 |
|---|---|
| 雑談 / 即答可能 | **reply_message** (無料) |
| 検索 < 3 秒 | **reply_message** (無料) |
| 検索 > 3 秒 | `showLoadingAnimation(60s)` で即 ack → **push_message** (課金対象) |

QA の月次利用量を監視し、Haiku で十分な簡易クエリは reply 内で完結するよう prompt 設計。

### 8.3 想定通信量

- 配信 (Phase 1): 日次 1 通 × 30 = 30 通/月 (無料枠内)
- QA (Phase 2): 10 質問/日 × 30 = 300 往復/月 (reply で無料、push 化時のみ課金)

### 8.4 フィードバック UI (Phase 3)

配信 Flex Message の各記事バブルに Postback ボタンを 2 個追加:

```
┌─────────────────────────┐
│ BigQuery Iceberg 統合 GA │
│ 1-2文要約...             │
│ #bigquery #iceberg       │
│ [詳しく読む] [👍] [👎]   │
└─────────────────────────┘
```

- Postback data: `action=feedback&article_id=<id>&signal=like|dislike`
- 押下で「フィードバック受付ました」を reply で即応答 (無料)
- 保存: SQLite `feedback` テーブル + analytics-platform に `business_event (action=feedback_received)` 二重化
- 学習反映 (Phase 3 で段階的):
  - F-37: 直近 7 日で 👎 が 👍 を上回るソース → `source_weight *= 0.8` を日次バッチで更新
  - F-38: 👎 されたタグ上位を relevance_scorer の system prompt に negative few-shot として追加
  - F-39: 👍 率から逆算して `RELEVANCE_THRESHOLD` を percentile ベース自動調整

---

## 9. 想定コスト (月次)

### Phase 1 (収集 + 配信のみ、ローカル)

| サービス | 使用量 | コスト |
|---|---|---|
| ローカル (Docker Compose) | 常時 | $0 |
| Claude API (Haiku 中心) | 150 件/日 × 30 日 | $3-5 |
| LINE Messaging API | 30 通/月 | 無料 |
| **Phase 1 合計** |   | **$3-5/月** |

### Phase 2 追加分 (QA)

| サービス | 使用量 | コスト |
|---|---|---|
| Embedding (sentence-transformers local) | CPU 4,500 件/月 | $0 (電気代除く) |
| Claude API (Haiku + Sonnet、QA 10 回/日) |   | $1-2 |
| **Phase 2 追加** |   | **$1-2/月** |

### Phase 4 (GCP 移行時、将来)

| サービス | 想定月額 |
|---|---|
| Cloud Run Jobs + Cloud Scheduler | 無料枠内 |
| BigQuery (ストレージ + クエリ) | 無料枠内 |
| GCS (raw/uploaded/payloads) | 無料枠内 |
| Secret Manager | ~$0.2 |
| Vertex AI Embedding | <$1 |
| Claude API (同上) | $4-7 |
| LINE Push (超過時) | 可変 |
| **Phase 4 合計目安** | **$5-10/月** |

---

## 10. フェーズ計画

### Phase 0 (前提)

- ✅ `lifeplanner-agent/services/llm_client.py` に prompt caching + `complete_messages` (PR #33)

### Phase 1 MVP (2-3 週間目安)

**目標**: 毎朝 JST 07:00 に、主要 5 ソース + arXiv の Top 7 + 1-2 論文が LINE に届く。

- [ ] プロジェクト初期化 (`pyproject.toml` / `Dockerfile` / `docker-compose.yml` / `Makefile` / `.env.example`)
- [ ] `config/sources.yaml` (Phase 1 初期 6 ソース)
- [ ] URL 正規化 + `article_id` 生成ユニットテスト
- [ ] RSS Collector (feedparser、ソース毎エラーハンドリング)
- [ ] arXiv Collector (`arxiv` SDK、3 秒間隔 + tenacity backoff)
- [ ] `analytics-platform` に `business_event (article_collected)` として emit
- [ ] dbt staging/marts (`stg_tech_news_articles`, `mart_articles_curated` の雛形)
- [ ] Relevance Scorer (Haiku 4.5、バッチ 10 件、`cache_system=True`)
- [ ] Summarizer (Haiku 4.5)
- [ ] Tagger (Haiku 4.5)
- [ ] Ranker (ルールベース)
- [ ] Flex Message builder + LINE Push
- [ ] `POST /internal/run-pipeline` エンドポイント
- [ ] `cron` + docker-compose でスケジュール実行
- [ ] `GET /healthz`
- [ ] security-platform 登録 (`inventory.yaml` / `scan.yaml`)
- [ ] ユニットテスト (collector / curator / url_normalizer)

### Phase 1.5 ソース拡充 (1-2 週間)

- [ ] GitHub Trending スクレイパ (requests + BeautifulSoup、失敗時アラート)
- [ ] GitHub Releases watchlist (PyGithub)
- [ ] Zenn 複数 topic / Qiita / はてブ / Reddit 追加
- [ ] 失敗ソースの週次レポート
- [ ] プロンプトキャッシュヒット率の monitoring (`analytics-platform` の `llm_call.cache_read_tokens`)

### Phase 2 インタラクティブ QA (2-3 週間)

- [ ] `curated_articles` に embedding 列追加 (Phase 2 着手時点のものを一括生成 → 以降 incremental)
- [ ] Embedder Protocol (local / Vertex AI 差替)
- [ ] sqlite-vec or duckdb-vss でベクトルインデックス
- [ ] LINE Webhook (`stock-analysis-agent` 流儀、署名検証 + 即 200)
- [ ] FastAPI BackgroundTasks で非同期 QA
- [ ] QA Agent (LangGraph: Intent → Rewrite → Retrieve → Rerank → Answer)
- [ ] Reply / Push 自動切替 (loading animation)
- [ ] `conversations` / `qa_history` SQLite テーブル
- [ ] prompt regression テスト (引用付き回答・ハルシネーション対策)

### Phase 3 ドメイン拡張 + フィードバック学習 (継続)

#### ドメイン拡張

- [ ] セキュリティドメイン (OWASP / CVE / Snyk)
- [ ] クラウドドメイン (GCP/AWS/Azure)
- [ ] LLM 動向ドメイン (Anthropic/OpenAI/DeepMind)
- [ ] ドメイン別配信時間設定
- [ ] 週次/月次ダイジェスト

#### フィードバック学習 (F-36 〜 F-39)

- [ ] Flex Message 各バブルに `action=feedback&article_id=...&signal=like|dislike` の Postback ボタン追加
- [ ] Postback Router で feedback 受信 → SQLite `feedback` テーブル + analytics-platform `business_event` に保存
- [ ] 日次バッチで 👎/👍 集計 → `sources.yaml` の source_weight を自動更新
- [ ] 👎 タグを relevance_scorer prompt の negative few-shot に注入
- [ ] `RELEVANCE_THRESHOLD` を 👍 率 percentile ベースで動的化 (デフォルトは 5.0 固定のまま、`DYNAMIC_THRESHOLD=true` で有効化)

### Phase 4 GCP 移行 (analytics-platform Phase 5+ 合流時)

- [ ] JSONL sink を GCS 直書きに切替
- [ ] dbt を `bigquery` target に差替
- [ ] sqlite-vec → BigQuery `VECTOR_SEARCH`
- [ ] Cloud Scheduler + Cloud Run Job (pipeline)
- [ ] Cloud Run Service (webhook)
- [ ] Secret Manager / Workload Identity

### Phase 5 公開化 (ずっと先)

- [ ] Firebase Auth
- [ ] LIFF でユーザ別ドメイン選択 UI
- [ ] プラン制限 / 有料化検討

---

## 11. セキュリティ

| 項目 | 対策 |
|---|---|
| LINE Webhook 偽装 (Phase 2+) | X-Line-Signature HMAC-SHA256 検証 |
| 不正ユーザー | `LINE_USER_IDS` 許可リスト |
| シークレット | `.env` (gitignore)、GCP 移行時は Secret Manager |
| スクレイピング rate limit | arXiv 3 秒間隔、GitHub Trending は 1 分間隔 |
| LLM ハルシネーション | 要約は原文 URL 必ず併記、QA は引用元記事を必ず添付 |
| API コスト暴騰 | `analytics-platform` の `llm_call.total_cost_usd` を dbt で集計、閾値 Slack 通知 |
| 重複配信 | article_id (正規化 URL hash) で idempotent、past 30 日と照合 |
| security-platform | `inventory.yaml` / `scan.yaml` に登録、gitleaks / bandit 適用 |

---

## 12. リスクと対策

| リスク | 影響 | 対策 |
|---|---|---|
| RSS ソース閉鎖/仕様変更 | 一部取得失敗 | ソース毎 try/except、週次で dead-link レポート |
| GitHub Trending HTML 変更 | スクレイパ停止 | 失敗アラート、Trendshift 等代替 API へフォールバック |
| LLM ハルシネーション | 誤った要約/回答 | 原文 URL 必須添付、QA 引用元記事必須 |
| API コスト暴騰 | 予算超過 | `llm_call.total_cost_usd` の日次集計、閾値通知 |
| LINE 超過 | Push 課金 | Phase 2 QA は reply 優先、push は要約短縮 |
| arXiv rate limit | 取得失敗 | 3 秒間隔 + tenacity backoff + 1 日 1 回まで |
| QA ヒット 0 件 | 回答不能 | Web 検索 fallback or 正直に「該当なし」と返答 |

---

## 13. 設定・運用

### 13.1 環境変数

```bash
# --- App ---
APP_ENV=dev
SERVICE_VERSION=0.1.0
LOG_LEVEL=INFO

# --- LINE ---
LINE_CHANNEL_SECRET=
LINE_CHANNEL_ACCESS_TOKEN=
LINE_USER_IDS=Uxxxx,Uyyyy    # 許可 userId

# --- LLM ---
ANTHROPIC_API_KEY=
LLM_MODEL=claude-haiku-4-5
LLM_MODEL_HEAVY=claude-sonnet-4-6

# --- analytics-platform ---
ANALYTICS_ENABLED=true
ANALYTICS_SERVICE_NAME=tech-news-agent
ANALYTICS_DATA_DIR=../analytics-platform/data
ANALYTICS_COMPRESS=false

# --- Embedding ---
EMBEDDING_PROVIDER=local        # local | vertex
EMBEDDING_MODEL=intfloat/multilingual-e5-base

# --- スケジューリング ---
PIPELINE_SCHEDULE_CRON="30 6 * * *"  # JST 06:30
```

### 13.2 起動

```bash
cd tech-news-agent
cp .env.example .env
# 各種シークレット設定
make install
make run            # FastAPI 起動 (port 8300)

# 手動パイプライン実行 (cron が叩く想定)
curl -X POST http://localhost:8300/internal/run-pipeline

# テスト
make test
make lint
```

### 13.3 監視

- `analytics-platform` の DuckDB で `llm_call` / `business_event` を見る
- `mart_source_coverage` で日次ソース別取得件数
- Phoenix (OTel) で LLM 呼出トレース

---

## 14. 既知の決定事項と開いた論点

### 決定済み

- ストレージは analytics-platform 一極 (SQLite は hot path のみ)
- Phase 1-3 は完全ローカル、GCP 移行は Phase 4 で analytics-platform Phase 5+ と合流
- **LLM クライアントは `llm-client/` として monorepo root に切り出し** (専用 PR、tech-news Phase 1 着手前に実施)。現在の唯一の利用者 lifeplanner-agent は path dep 先を切替
- LangGraph は Phase 2 QA から。Phase 1 は関数チェーン
- MCP は MVP で不採用、Phase 2 以降で必要に応じて
- プロジェクト名は `tech-news-agent` (ドメイン拡張の将来性のため)
- **ソース別 ranker weight は `sources.yaml` の `priority` (1/2/3) から数値ウェイト (0.7/1.0/1.5) に Ranker で変換** (§4.4)。LLM 判定は Phase 3 以降にフィードバック学習で補正
- **フィードバック UI は記事バブル単位の 👍/👎 Postback** (§8.4)。SQLite `feedback` + analytics-platform `business_event` の二重保存
- **arXiv カテゴリは Phase 1 で `cs.DB` / `cs.DC` / `cs.IR` の 3 つ**。Phase 1.5 で `cs.LG` + キーワードフィルタ (`data pipeline` / `vector search` / `embedding` / `RAG` / `lakehouse` 等) 併用で追加
- **関連度閾値は Phase 1 で `RELEVANCE_THRESHOLD=5.0` 固定** (環境変数で上書き可)。Phase 3 の F-39 で 👍/👎 率 percentile ベース動的化を別フェーズタスクとして実施

### 開いた論点 (実装着手時に決めれば良いレベル)

現時点で Phase 1 着手をブロックする論点なし。実装中に出てきた細部はコミット時に判断する。

---

## 15. 将来統合ポイント — security-platform

モノレポの `security-platform` は既に自プロジェクトのセキュリティ関連情報収集・配信機能を持つ:

| レイヤ | 既存機能 |
|---|---|
| Collector | NVD / GitHub Advisory / OSV / VulnerableMCP から **CVE** 収集 |
| Analyzer | `config/inventory.yaml` の monorepo 部品と CVE 照合 → 自スタックにヒットするものだけ抽出 |
| Notifier | Slack / LINE Notify / Email の daily/weekly digest |
| Dashboard | `http://localhost:8000` で可視化 |

### 15.1 tech-news-agent との棲み分け

| 項目 | security-platform | tech-news-agent (Phase 3 security) |
|---|---|---|
| 対象 | **自プロジェクトに影響する脆弱性** | **業界の一般セキュリティニュース** |
| データソース | CVE DB (NVD/Advisory/OSV/VulnerableMCP) | RSS 記事 (OWASP/Snyk Blog 等) |
| 粒度 | 個別 CVE | 記事 (how-to / 解説) |
| アクション性 | 高 (要対応) | 低 (情報共有・学習) |

両者は役割が直交するため、**片方に吸収するのではなく連携する**方針。

### 15.2 連携シナリオ (Phase 3 セキュリティドメイン着手時)

採用案: **中疎結合 (CVE データを tech-news が取り込み、自スタックヒット CVE + 業界ニュースを一つの Flex Message carousel で配信)**

具体タスク (tech-news-agent Phase 3 のセキュリティドメイン追加と同時に実施):

- [ ] `line-publisher/` モジュールを monorepo root に切り出し (Flex Message builder + Messaging API ラッパの共通化)
- [ ] tech-news-agent Collector に `SecurityPlatformCVECollector` 追加:
  - 入力: security-platform の SQLite `vulnerabilities` テーブル (path dep 参照、または analytics-platform 経由で subscribe)
  - 自スタック影響あり (inventory 照合済み) フラグを `attributes` に保持
- [ ] tech-news Publisher で自スタックヒット CVE は **バッジ「⚠️ 自スタック影響あり」** を Flex バブルに付与、優先配信
- [ ] security-platform の既存 Notifier (`src/notifier/digest.py`) は段階的に tech-news に委譲、または並走 (Slack/Email は security-platform のまま、LINE は tech-news に寄せる)

### 15.3 LINE Notify 終了問題 (先行対処が必要)

**⚠️ security-platform の LINE 通知は `LINE Notify` を使っているが、LINE Notify は 2025/03/31 にサービス終了済**。`src/notifier/line.py` は現時点で動作不能。

PR #36 マージ後、**tech-news-agent Phase 1 着手前**に以下を別 PR で先行対処:

- [ ] `security-platform/src/notifier/line.py` を LINE Notify API → LINE Messaging API に移行
  - 既存の `LineBotClient` パターン (`stock-analysis-agent` / `piyolog-analytics` 参照) を踏襲
  - Push Message で CVE digest を配信
  - LINE Channel secret / access token の Secret Manager / `.env` 管理
- [ ] `security-platform/config/` に `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` 追加
- [ ] 既存の `LINE_NOTIFY_TOKEN` 設定は廃止予定フラグを立てる
- [ ] LINE 通知が出るテスト (monkeypatch で送信先を stub)
- [ ] README / `.env.example` 更新

この移行で使う LINE クライアントは、Phase 3 で `line-publisher/` に共通化する前提 (最初は security-platform 内に薄く書き、Phase 3 統合時にリファクタ)。

---

## 16. 参考資料

- arXiv API: https://info.arxiv.org/help/api/index.html
- LINE Flex Message: https://developers.line.biz/ja/docs/messaging-api/using-flex-messages/
- LINE rich menu: https://developers.line.biz/ja/docs/messaging-api/using-rich-menus/
- Claude prompt caching: https://docs.claude.com/en/docs/build-with-claude/prompt-caching
- sqlite-vec: https://github.com/asg017/sqlite-vec
- DuckDB VSS extension: https://duckdb.org/docs/extensions/vss
- 先行モノレポエージェント: `stock-analysis-agent` / `lifeplanner-agent` / `hotcook-agent` / `piyolog-analytics`

---

*ステータス: Phase 1 MVP 実装完了。Phase 1.5 以降は §10 のチェックリスト順で着手。*

---

## 17. Phase 1 実装メモ

### ローカル起動手順

```bash
cd tech-news-agent
cp .env.example .env
# .env を編集: LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_IDS / ANTHROPIC_API_KEY
make install
make run                # 別ターミナルで:
make pipeline           # POST /internal/run-pipeline で 1 回実行
```

`LLM_MOCK_MODE=true` で LLM 呼出しをスキップできる (Mock クライアントが JSON 形式外を返すので scorer は 0 点扱い → 配信空振りの動作確認用)。

### 実装構成

```
tech-news-agent/
├── app/
│   ├── main.py                        FastAPI + lifespan
│   ├── config.py                      Settings (pydantic-settings)
│   ├── models.py                      RawArticle / CuratedArticle / Digest
│   ├── collectors/
│   │   ├── rss.py                     feedparser + httpx + tenacity backoff
│   │   └── arxiv_source.py            arxiv SDK + rate_limit_seconds=3
│   ├── curator/
│   │   ├── prompts.py                 SCORER_SYSTEM / SUMMARIZER_SYSTEM / TAGGER_SYSTEM
│   │   ├── scorer.py                  バッチ 10 件 + cache_system=True
│   │   ├── summarizer.py              1 記事 1 呼出
│   │   ├── tagger.py                  english kebab-case
│   │   └── ranker.py                  ルールベース Top N
│   ├── publisher/
│   │   ├── flex_builder.py            carousel + header bubble
│   │   └── line_client.py             LineBotSdkClient (Push 専用)
│   ├── repositories/
│   │   ├── dedup_repo.py              SQLite `delivered_articles` + `digests`
│   │   └── schema.sql
│   ├── services/
│   │   ├── url_normalizer.py          UTM 除去 + sha256[:32]
│   │   ├── source_config.py           sources.yaml ロード + priority→weight
│   │   ├── llm_factory.py             llm-client への bind (on_call → analytics-platform)
│   │   └── pipeline.py                オーケストレータ
│   ├── instrumentation/               analytics-platform セットアップ
│   └── routes/
│       ├── health.py                  GET /healthz
│       └── pipeline.py                POST /internal/run-pipeline
├── config/sources.yaml                Phase 1 初期 5 RSS + arXiv 3 category
├── tests/                             38 件 (url_normalizer 10 / source_config 4 / dedup 5 / rss 3 / ranker 5 / flex 5 / pipeline 6)
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── Makefile
└── .env.example
```

### analytics-platform に載るイベント

1 パイプライン実行で:
- `business_event(action=articles_collected)` × 1 (概要)
- `business_event(action=article_collected)` × N (個別記事メタデータ、`content_preview` 含む)
- `business_event(action=article_curated)` × M (スコア / 要約 / タグ、通過分のみ)
- `business_event(action=digest_delivered)` × 1 (配信結果、`article_ids` 含む)
- `llm_call` × 数十回 (scorer / summarizer / tagger、`on_call` コールバック経由)

`analytics-platform/data/raw/service_name=tech-news-agent/...` に JSONL として書き出され、`dbt-duckdb` で staging/marts に流せる状態になる (dbt モデル本体は Phase 1.5 で整備予定)。

