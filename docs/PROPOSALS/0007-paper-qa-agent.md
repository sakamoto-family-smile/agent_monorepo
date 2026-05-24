# PROPOSAL-0007: 論文検索 QA エージェント `paper-qa-agent` と共通基盤 `paper-platform`

| | |
|---|---|
| **Status** | Draft |
| **Author** | @kurama554101 |
| **Created** | 2026-05-24 |
| **Updated** | 2026-05-24 |
| **Target** | `paper-qa-agent` (新規 LINE Bot)、`paper-platform` (新規 cross-agent 共通基盤、path dep ライブラリ) |
| **Related PRs** | (none yet、本 PR が初版) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

arxiv / Semantic Scholar 等を一次ソースとして、LINE Bot 経由で **論文検索・構造化要約・本文 Q&A** を会話的に提供するエージェント `paper-qa-agent` を新設する。Phase 1 は ML / NLP に絞り、`Domain` インターフェースを通じて将来 bio / physics / 経済学等に拡張可能な設計とする。

データ取得層 (クロール / 各種 API クライアント / ID 正規化 / 重複排除 / 埋め込み / pgvector ストア / ランカ) は将来の他エージェント (`tech-news-agent` の arxiv crawler、`kanie-lab-agent` の paper-search MCP ラッパ) からも再利用する想定で **`paper-platform`** として path dep ライブラリ化する (`fujisawa-platform` と同じ作法)。Cloud SQL は `driving-license-bot` 所有の共有 instance を `fujisawa-platform` と同じ data-source 方式で参照し、新規 instance を起こさない (instance 月額増分 ¥0)。

## 2. Motivation

### 現状の課題

論文を起点とした既存実装は複数あるが、互いに独立した実装でデータ取得・正規化のロジックを重複させている。

| エージェント | 論文関連の機能 | データ取得方式 |
|---|---|---|
| `kanie-lab-agent` | 入試準備の論文サーベイ (Web UI) | arxiv / Semantic Scholar / paper-search MCP を `Claude Agent SDK` 経由で個別呼出 |
| `tech-news-agent` | 日次論文ダイジェスト LINE 配信 | 独自の arxiv crawler (`cs.DB` / `cs.DC` / `cs.IR`) |
| (参考) `stock-analysis-agent` | 株価分析 LINE Bot + 法定開示書類分析 | EDINET API → XBRL (proposal 0006、 別ドメインだが LINE + Cloud Run + agent service の構造は同型) |

両者 (kanie-lab / tech-news) とも arxiv / Semantic Scholar への rate-limit 遵守クロール、ID 正規化、重複排除、関連度スコアリングのロジックを **重複** して持っている。 stock-analysis-agent は別ドメイン (金融) なので paper-platform の対象外だが、 LINE Bot + Cloud Tasks + agent service + Cloud SQL 共有という同型の構造を持ち、 共通部品 (LINE handler / Cloud Tasks dispatcher / observability) の cross-agent 抽出余地は将来別 proposal で検討する。さらにユーザ視点で見ると、以下の体験は現状どのシステムでも提供されていない:

1. LINE で **会話的** に論文検索 (例: 「最近の RLHF で人間ラベル減らすやつ」)
2. 各論文の **構造化要約** (3 行 TL;DR + 手法 + 結果 + Limitations)
3. 選んだ論文に対する **本文 Q&A** (例: 「損失関数は？」 → §3.2 を引いて出典付き回答)

### 放置するとどうなるか

- 論文系の機能追加のたびにクロール基盤を再発明し続ける
- arxiv / Semantic Scholar への二重 fetch (rate-limit 規約上望ましくない、技術的迷惑)
- 個人ユースで一番痒い「**移動中にスマホで論文を漁る**」体験が穴のまま

### 2.1 Goals

- [ ] LINE Bot で自然文クエリ → 関連論文 Top 5 を Flex Message Carousel で返却 (テストセット 20 問で `recall@5 >= 0.8`)
- [ ] 各論文に 4 段構造の要約 (TL;DR / Method / Key Finding / Limitations) をワンタップで展開可能
- [ ] Phase 2 で、選んだ論文に対し本文セクションを引いた出典付き Q&A を提供 (テストセット 30 問で `citation precision >= 0.9`)
- [ ] arxiv + Semantic Scholar のクロール・正規化を `paper-platform` に切り出し、他エージェントから再利用可能にする
- [ ] Cloud SQL は `driving-license-bot` 共有 instance を流用し、月額増分 ¥0 (新規 DB / user のみ)
- [ ] Phase 1 月額運用コストの目標は §5.4 コスト節で再見積もり中 (初期目標 ¥6,500 は LLM コスト過小評価のため修正)。 50 検索/日 × 二段 LLM ranking で ~¥33,000/月、 Sonnet 単段に下げれば ¥10,000〜13,000/月 まで圧縮可能。 Approval 前に **個人運営として許容するコスト水準を確定する** 必要あり

### 2.2 Non-Goals

- **Google Scholar クロール**: 公式 API がなく規約上スクレイピング不可。OpenAlex / Semantic Scholar で代替
- **論文 PDF の社外配布**: 出典 URL の提示までで、PDF 本文の LINE 上 forward は行わない
- **Phase 1 での全ドメイン対応**: ML/NLP のみ。bio / physics 等は Phase 5
- **マルチユーザー / 共有しおり**: Phase 5 以降
- **本番デプロイの GCP 以外への展開**: AWS / Azure ポータビリティは目指さない (Vertex AI Claude 依存を許容)
- **論文の自動レビュー / 査読**: 「この論文は良いか悪いか」の価値判断は LLM に出させない (hallucination + 倫理リスク)
- **Phase 1 での本文 RAG / QA**: メタデータ + 要約まで。RAG は Phase 2 で導入

---

## 3. Proposal

### 3.1 User Stories

#### 3.1.1 ストーリー 1: 通勤電車で「最近の RLHF」を漁る

> **ユーザ**: 「最近の RLHF で人間ラベル減らすやつ教えて」
>
> **Bot** (約 8 秒後): Flex Carousel で 5 件返却
>   - [1] *Direct Preference Optimization* (Rafailov+, 2023 NeurIPS, cited 2.1k)
>   - [2] *RLAIF: Scaling RLHF with AI Feedback* (Lee+, 2023)
>   - ... (各 bubble に「3 行要約」「QA 開始」「PDF」ボタン)
>
> **ユーザ**: [1] の「3 行要約」をタップ
>
> **Bot** (約 3 秒後):
> ```
> TL;DR: 報酬モデルを介さず、好み対 (y_w, y_l) を直接最尤化することで RLHF を簡素化。
> Method: KL 制約付き log-ratio を最大化する閉形式損失を導出。
> Key Finding: PPO ベース RLHF と同等以上の対話品質、訓練コスト 1/3。
> Limitations: 好みデータの分布外への汎化は未検証。
> ```

#### 3.1.2 ストーリー 2: 選んだ論文に Q&A (Phase 2+)

> **ユーザ**: [1] の「QA 開始」をタップ
>
> **Bot**: 「論文の本文を読み込んでいます (約 30 秒)…」 (LINE Push)
>
> **Bot** (約 30 秒後): 「準備完了。質問をどうぞ」
>
> **ユーザ**: 「損失関数は具体的にどう書くの？」
>
> **Bot** (約 8 秒後):
> ```
> 論文 §3.2 によれば、DPO 損失は以下:
>   L_DPO(πθ; π_ref) = -E[(x, y_w, y_l)~D][
>     log σ(β · log(πθ(y_w|x)/π_ref(y_w|x))
>         - β · log(πθ(y_l|x)/π_ref(y_l|x)))
>   ]
> σ はシグモイド、β=0.1 が論文の既定値 (§4.1)。
> ```
> (出典: arxiv:2305.18290, §3.2, p.5)

#### 3.1.3 ストーリー 3: フォローアップ (Phase 2+)

> **ユーザ**: 「他のベースラインとどう違う？」 (直前の `active_paper` が DPO)
>
> **Bot** (約 8 秒後): 「論文の §5.1 表 1 によれば、PPO-RLHF と比較して…」 + 出典

### 3.2 Notes / Constraints / Caveats

- **LINE 1 ターン = 1 メッセージ制約**: 重い処理は webhook 内で完結させず、Cloud Tasks 経由で agent-service にディスパッチ、Push API で結果通知する非同期パターン (`driving-license-bot` Phase 1 設計と同方針)。webhook は 1 秒以内に 200 OK を返す
- **Cloud Run cold start**: agent-service は `min-instances=1` 必須。line-bot-service は webhook 受信だけなので `min=0` で OK
- **ドメイン拡張インターフェース**: Phase 1 では `Domain` interface 自体を実装するが、その実装は `ml_nlp` のみ。新ドメイン追加時は `paper-qa-agent` 本体に手を入れず、`paper-platform/domains/<name>.py` + YAML 1 ブロック追加で済むようにする
- **pgvector db 単位の extension**: `driving-license-bot` で instance レベルでは `CREATE EXTENSION vector` 済だが、新規 DB (`paper_qa_db`) には別途流す必要 (PostgreSQL の extension は DB スコープ)
- **PDF 著作権**: arxiv / OA (CORE) は OK。商業出版社 PDF は本文 RAG の対象外、メタデータ + 出典 URL 表示まで
- **Hallucination ガード**: QA Agent は pgvector の retrieve score が閾値以下のセクションをコンテキストに含めない。コンテキスト 0 件なら「この論文に該当記述なし」と明示
- **個人運営の rate cap**: per LINE userId で `daily_searches <= 30`、`daily_qa_calls <= 50` を Firestore で管理。超過時は silent throttle (「明日また」とだけ返信)
- **共有 Cloud SQL のオーナーシップ**: `driving-license-bot` が instance を所有しているため、tier 変更・PG バージョン上げ等の **共有部分の変更は driving-license-bot 側で実施**。consumer 側 (本案) は `data source` 参照のみ
- **`tech-news-agent` / `kanie-lab-agent` の paper-platform 移管**: Phase 4 で別 proposal として実施。本 proposal では新規系統だけ作り、既存は変更しない。 移管前提は本 proposal で **固定しない** — Phase 4 開始時に当該エージェントの owner と現状の利用状況を改めて確認したうえで、 移管 vs 並存 vs 廃止のいずれかを再判断する

### 3.3 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| arxiv API への過剰アクセス (規約違反) | High | `paper-platform/crawler/PoliteFetcher` (rate-limit 3 秒/req)、User-Agent に連絡先明示。`tech-news-agent` の作法を踏襲 |
| Semantic Scholar の rate-limit (1 req/sec 無料枠) | Medium | 同上 + `asyncio.Semaphore` で並列度制限。429 で exponential backoff (2s/4s/8s) |
| pgvector 共有 instance の他システム道連れ性能劣化 | Medium | Cloud SQL CPU usage を monitoring、70% 超を 1 日継続で tier 上げ (`db-f1-micro` → `db-custom-1-3840`)。pgvector query は ivfflat で 100ms 以下を目標 |
| LLM hallucination で誤った要約・QA 回答 | High | Pydantic schema による structured output 強制、QA は retrieve score 閾値以下なら no-answer、評価ハーネスで `citation precision` 計測 |
| Vertex AI 連続呼出でコスト爆発 | Medium | Sonnet 4.6 主体 + Opus 4.7 は ranking の精ランクと QA 時のみ。1 conversation = 最大 10 tool iterations。per-user daily quota |
| LINE webhook 署名検証漏れ | High | `line-bot-sdk v3` の `WebhookHandler` を素直に使い、`InvalidSignatureError` で 401。Unit test カバー |
| 個人運営なのに「研究指導 / 査読」と誤認される | Medium | LINE Bot プロフィール / 初回返信に「学習支援ツール、評価判断はしない」を明示 |
| Cloud SQL ディスク満杯 (10GB) | Medium | `instance.disk.bytes_used >= 7GB` で alert、`driving-license-bot` 側の `cloudsql_disk_size_gb` を 20 に bump (in-place、ダウンタイムなし) |
| 共有 instance の `terraform destroy` 事故 | High | 全 consumer (本案含む) が `deletion_policy = "ABANDON"` を `google_sql_database` / `google_sql_user` に必須付与 (`fujisawa-platform` と同方針) |

---

## 4. Design Details

### 4.1 アーキテクチャ概略

```
LINE Platform
   │
   ▼
┌──────────────────────────────────────────────────────┐
│ Cloud Run: paper-qa-line-bot (FastAPI, min=0)        │
│   ・LINE webhook 受信 → 即時 200 OK                   │
│   ・analytics-platform: AnalyticsLogger              │
│   ・Cloud Tasks にディスパッチ                          │
└──────────────────┬───────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────┐
│ Cloud Tasks: paper-qa-queue                          │
│   ・retry / DLQ / rate-limit per LINE user           │
└──────────────────┬───────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────┐
│ Cloud Run: paper-qa-agent-service (min=1, max=3)     │
│   (Claude Agent SDK + paper-platform path dep)       │
│                                                       │
│  Orchestrator (Sonnet 4.6)                           │
│   ├── Query Refinement (Sonnet, domain vocab inj.)   │
│   ├── Retrieval (paper-platform.sources.*)           │
│   │     ・arxiv + Semantic Scholar 並列              │
│   │     ・hybrid: BM25 (tsvector) + dense (pgvector) │
│   │     ・RRF (Reciprocal Rank Fusion) で合成        │
│   ├── Ranking (Sonnet → top 10 → Opus 4.7 → top 5)   │
│   ├── Summarization (Sonnet, Pydantic schema)        │
│   └── QA Agent (Opus 4.7, Phase 2+)                  │
│                                                       │
│  全 MCP 呼出 → security-platform MCP Proxy 経由        │
└──┬───────────────────────────────────────────────────┘
   │
   ├──► Vertex AI: Claude (Sonnet 4.6 / Opus 4.7)
   ├──► Vertex AI: text-embedding-004 (768d)
   │
   ├──► Cloud SQL (driving-license-bot 共有 instance):
   │     paper_qa_db (新規 database)
   │      - papers, paper_embeddings, paper_sections (P2+),
   │        paper_citations
   │
   ├──► Firestore:
   │     conversations/{family_id}/turns/{turn_id}
   │     sessions/{line_user_id}
   │     rate_limits/{line_user_id}/{date}
   │
   ├──► GCS (Phase 2+):
   │     gs://paper-qa-pdf-cache/<arxiv_id>.pdf
   │     gs://paper-qa-pdf-cache/structured/<id>.json
   │
   └──► analytics-platform GCS / BigQuery (JSONL)
        ・llm_call / tool_invocation
        ・business_event(paper_recommended, summary_shown,
                         qa_answered)

┌──────────────────────────────────────────────────────┐
│ Cloud Run Job: paper-ingestion-worker (Phase 2+)     │
│   ・Cloud Tasks 経由で PDF URL 受信 → docling 抽出    │
│   ・section embedding → pgvector upsert               │
└──────────────────────────────────────────────────────┘
```

### 4.2 データモデル

新規 database `paper_qa_db` を `driving-license-bot` 共有 Cloud SQL instance に追加。`pgvector` extension は db スコープなので新規に有効化が必要。

```sql
-- Phase 1
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE papers (
  id              TEXT PRIMARY KEY,           -- canonical id: "arxiv:2305.18290" / "doi:..."
  arxiv_id        TEXT,
  doi             TEXT,
  s2_id           TEXT,
  title           TEXT NOT NULL,
  abstract        TEXT,
  authors         JSONB,                       -- [{name, s2_author_id}]
  venue           TEXT,
  year            INT,
  published_at    DATE,
  citation_count  INT,                         -- Semantic Scholar 由来
  primary_category TEXT,                       -- "cs.LG" 等 (arxiv)
  domain          TEXT NOT NULL DEFAULT 'ml_nlp',
  pdf_url         TEXT,
  gcs_pdf_uri     TEXT,                        -- Phase 2+
  ingestion_status TEXT NOT NULL DEFAULT 'metadata_only',
                                               -- 'metadata_only' | 'pdf_indexed' | 'pdf_failed'
  metadata_hash   TEXT,                        -- 差分検知 (fujisawa-platform 流)
  last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX papers_arxiv_id_idx ON papers (arxiv_id);
CREATE INDEX papers_doi_idx ON papers (doi);
CREATE INDEX papers_domain_year_idx ON papers (domain, year DESC);
CREATE INDEX papers_title_tsv_idx ON papers
  USING GIN (to_tsvector('english', title || ' ' || COALESCE(abstract, '')));

CREATE TABLE paper_embeddings (
  paper_id     TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  kind         TEXT NOT NULL,                  -- 'title_abstract' (P1) / 'section' (P2+)
  section_idx  INT NOT NULL DEFAULT 0,
  embedding    VECTOR(768) NOT NULL,
  PRIMARY KEY (paper_id, kind, section_idx)
);
CREATE INDEX paper_embeddings_ivfflat
  ON paper_embeddings USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- Phase 2+
CREATE TABLE paper_sections (
  paper_id      TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  section_idx   INT NOT NULL,
  section_title TEXT,
  page_start    INT, page_end INT,
  content       TEXT,
  PRIMARY KEY (paper_id, section_idx)
);

CREATE TABLE paper_citations (
  src_paper_id  TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  dst_paper_id  TEXT NOT NULL,                 -- 外部論文も含む = REFERENCES つけない
  PRIMARY KEY (src_paper_id, dst_paper_id)
);
```

Firestore スキーマ:

```
conversations/{family_id}/turns/{turn_id}
  - timestamp: Timestamp
  - line_user_id: string
  - intent: 'search' | 'summarize' | 'qa' | 'follow_up'
  - query: string
  - result_paper_ids: [string]      (P1: 検索結果の id 一覧)
  - answer_text: string             (P2+: QA の回答本文)
  - citations: [{paper_id, section, score}]   (P2+)

sessions/{line_user_id}
  - active_paper_id: string | null
  - last_query: string
  - last_result_paper_ids: [string]
  - domain: 'ml_nlp'
  - updated_at: Timestamp
  - ttl_at: Timestamp               (24 時間 TTL)

rate_limits/{line_user_id}/daily/{YYYY-MM-DD}
  - search_count: int
  - qa_count: int
  - ttl_at: Timestamp               (3 日 TTL)
```

### 4.3 API

`paper-qa-line-bot`:
- `POST /api/line/webhook` — LINE Messaging API webhook。署名検証 → intent 分類 → Cloud Tasks 投入 → 200 OK 即返却
- `GET /healthz` — readiness probe

`paper-qa-agent-service`:
- `POST /internal/process` — Cloud Tasks から呼ばれる。`{line_user_id, message, intent_hint?}` を受け、Orchestrator を起動して結果を LINE Push API で送信
- `GET /healthz` — readiness probe

外部公開エンドポイントは LINE webhook のみ。`/internal/process` は `Cloud Run IAM invoker` で Cloud Tasks SA からのみ許可。

### 4.4 主要モジュール

#### 4.4.1 `paper-platform/` (新規、path dep ライブラリ)

```
paper-platform/
├── pyproject.toml
├── paper_platform/
│   ├── __init__.py
│   ├── models.py            ← Paper / Section / Citation の dataclass
│   ├── domains/
│   │   ├── base.py          ← Domain Protocol
│   │   ├── ml_nlp.py        ← Phase 1 実装
│   │   └── registry.py      ← YAML → Domain instance
│   ├── sources/
│   │   ├── base.py          ← PaperSource Protocol
│   │   ├── arxiv.py         ← Phase 1
│   │   ├── semantic_scholar.py  ← Phase 1
│   │   ├── openalex.py      ← Phase 3+
│   │   ├── core.py          ← Phase 3+ (PDF 取得)
│   │   └── crossref.py      ← Phase 3+
│   ├── crawler/
│   │   ├── polite_fetcher.py  ← fujisawa-platform から流用
│   │   └── rate_limiter.py
│   ├── normalize/
│   │   ├── identity.py      ← canonical_id (DOI > arxiv > S2 > title-hash)
│   │   └── dedup.py
│   ├── embedding/
│   │   ├── vertex_client.py
│   │   └── mock_client.py
│   ├── store/
│   │   ├── base.py
│   │   ├── pgvector_store.py
│   │   └── in_memory_store.py
│   ├── ranker/
│   │   ├── rule_based.py    ← citation × recency × source_weight
│   │   ├── llm_ranker.py    ← Sonnet (粗) / Opus (精) の二段
│   │   └── hybrid.py        ← BM25 + dense の RRF
│   └── pdf/                 ← Phase 2+
│       ├── fetcher.py
│       ├── docling_parser.py
│       └── section_chunker.py
├── tests/
└── README.md
```

##### `Domain` Protocol

```python
# paper_platform/domains/base.py
from typing import Protocol

class Domain(Protocol):
    name: str                          # "ml_nlp" | "bio" | "physics" | ...
    arxiv_categories: list[str]        # ["cs.LG", "cs.CL", "cs.AI", "stat.ML"]
    extra_sources: list[str]           # ["acl_anthology"]
    source_weights: dict[str, float]   # ranking 用の重み
    recency_half_life_days: int        # ML は速い (180 日)、医学は遅い (730 日)
    citation_normalization: str        # "field_weighted" | "raw"
    vocabulary_hints: list[str]        # query refinement の domain prior
    embedding_model: str               # 既定 text-embedding-004 を上書き可
```

##### domain YAML 設定

```yaml
# paper-platform/config/domains.yaml
domains:
  ml_nlp:
    arxiv_categories: [cs.LG, cs.CL, cs.AI, stat.ML]
    extra_sources: []
    source_weights: { arxiv: 1.0, semantic_scholar: 0.9 }
    recency_half_life_days: 180
    vocabulary_hints: [transformer, RLHF, in-context, alignment, ...]
  # Phase 5 追加例 (未実装):
  # bio:
  #   arxiv_categories: [q-bio.*]
  #   extra_sources: [biorxiv, pubmed]
  #   recency_half_life_days: 730
```

#### 4.4.2 `paper-qa-agent/` (新規、consumer)

```
paper-qa-agent/
├── pyproject.toml   # [tool.uv.sources] paper-platform = { path = "../paper-platform" }
├── Dockerfile
├── cloudbuild.yaml
├── terraform/
│   ├── apis.tf
│   ├── cloudsql.tf   ← driving-license-bot 共有 instance の data source + paper_qa_db
│   ├── cloud_run.tf  ← line-bot service + agent-service
│   ├── cloud_tasks.tf
│   ├── secrets.tf
│   ├── iam.tf
│   ├── wif.tf
│   └── variables.tf
├── app/
│   ├── main.py             ← FastAPI app, lifespan
│   ├── line/
│   │   ├── webhook.py      ← /api/line/webhook
│   │   └── push.py         ← Flex Message 組み立て
│   ├── tasks/
│   │   └── dispatcher.py   ← Cloud Tasks enqueue
│   ├── agent/
│   │   ├── orchestrator.py
│   │   ├── query_refinement.py
│   │   ├── retrieval.py    ← paper_platform.sources.* を呼ぶ
│   │   ├── ranking.py      ← Sonnet (top10) + Opus (top5) の二重 ranker
│   │   ├── summarization.py ← Pydantic schema validated
│   │   ├── qa.py           ← Phase 2+
│   │   ├── llm_routing.py  ← stage → model 対応表
│   │   └── prompts/
│   ├── repositories/
│   │   ├── firestore_sessions.py
│   │   ├── firestore_rate_limit.py
│   │   └── pg_papers.py    ← paper_platform.store.pgvector_store を wrap
│   ├── eval/
│   │   ├── testset.yaml    ← 20 問の ML/NLP gold queries
│   │   └── recall_at_k.py  ← 評価ハーネス
│   └── config.py
├── scripts/
│   └── eval.py
└── tests/
```

##### モデル選定 routing

```python
# app/agent/llm_routing.py
from enum import Enum

class Stage(str, Enum):
    QUERY_REFINEMENT = "claude-sonnet-4-6"   # 軽い分類なので Sonnet
    RANKING_COARSE   = "claude-sonnet-4-6"   # batch 10 件 × 5 並列
    RANKING_FINE     = "claude-opus-4-7"     # top 10 → top 5
    SUMMARIZATION    = "claude-sonnet-4-6"   # 構造化要約、schema validated
    QA               = "claude-opus-4-7"     # 精度優先 (Phase 2+)
```

##### Summarization の構造化出力

```python
from pydantic import BaseModel, Field

class PaperSummary(BaseModel):
    tldr: str        = Field(..., max_length=200, description="3 行以内の概要")
    method: str      = Field(..., max_length=200, description="提案手法を 1 文")
    key_finding: str = Field(..., max_length=200, description="主要結果を 1 文")
    limitations: str = Field(..., max_length=200, description="限界・将来課題、なければ '不明'")
```

`anthropic` SDK の `tool_use` で schema を強制し、不正レスポンスは即 retry。

### 4.5 Test Plan

- **Unit**:
    - `paper_platform.normalize.identity.canonical_id()` の DOI > arxiv > S2 > title-hash 優先順位
    - `paper_platform.ranker.hybrid.rrf()` の RRF スコア計算
    - `paper_platform.ranker.rule_based.compute_score()` の `llm × log(1+cite) × exp(-age/half_life) × source_w` 計算
    - `app.agent.summarization.parse_response()` の Pydantic schema 検証 (壊れた JSON で例外を投げる)
    - `app.line.push.build_flex_message()` のサイズ制約 (1 bubble ≤ 200 chars)

- **Integration** (pytest + testcontainers):
    - `paper-platform/store/pgvector_store.py`: ローカル PostgreSQL コンテナで upsert + similarity search
    - `app/agent/retrieval.py`: 模擬 arxiv / Semantic Scholar レスポンスでハイブリッド検索が動く
    - LINE webhook stub: 署名検証 → Cloud Tasks 投入が起きる (mock Tasks client)

- **Evaluation (CI 内モック、週次で実 API)**:
    - `app/eval/testset.yaml` の 20 クエリで `recall@5 >= 0.8` (mock embedding でも実行可、本番モデルで週次)
    - QA (Phase 2+): 30 質問の `citation precision >= 0.9`、`hallucination rate <= 5%`

- **Manual / E2E**:
    - 実 LINE Bot に「最近の RLHF で人間ラベル減らすやつ」と入力 → 10 秒以内に 5 件返却
    - 各 bubble の「3 行要約」ボタンが動く
    - per-user rate limit 超過時に silent throttle される
    - 同じクエリを 2 回投げて、ranking 結果の上位 5 件のうち 4 件以上が一致 (再現性)

### 4.6 Migration / Rollback

- **新規 system のためマイグレーション不要**。`paper_qa_db` は新規作成、初期データなし
- **paper-platform は新規 path dep**、既存エージェントの依存を変更しない (Phase 4 で `tech-news-agent` / `kanie-lab-agent` を移管する別 proposal を起こす)
- **ロールバック**: `terraform destroy` で `paper-qa-agent` の Cloud Run / Cloud Tasks / Firestore コレクションを撤去。`paper_qa_db` は `deletion_policy = ABANDON` のため共有 instance には残るので、必要なら `psql` から手動 `DROP DATABASE paper_qa_db CASCADE` を実行
- **env 追加**:
    - `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN`
    - `GOOGLE_CLOUD_PROJECT` / `VERTEX_AI_LOCATION` (us-east5)
    - `MCP_PROXY_URL`
    - `CLOUD_SQL_INSTANCE_CONNECTION_NAME` (driving-license-bot 共有 instance)
    - `PAPER_QA_DB_USER` / `PAPER_QA_DB_PASSWORD` (Secret Manager 経由、`paper_qa_app_user` / `paper_qa_etl_user`)
    - `ANALYTICS_*` (analytics-platform 連携)
    - `PAPER_QA_DOMAIN` = "ml_nlp" (Phase 1 既定)

### 4.7 Feature Enablement

| flag | 既定 | 用途 |
|---|---|---|
| `PAPER_QA_ENABLED` | `false` | `false` で `/api/line/webhook` は 503 (本番投入前の安全装置) |
| `PAPER_QA_DOMAIN` | `ml_nlp` | 単一ドメイン運用 (Phase 1)。複数指定は Phase 5 |
| `PAPER_QA_QA_MODEL` | `opus-4-7` | コスト圧縮したい場合 `sonnet-4-6` に下げる (Phase 2+) |
| `PAPER_QA_RANKING_USE_OPUS` | `true` | `false` で Sonnet 単段ランキング (精度低下、コスト圧縮) |
| `PAPER_QA_PDF_INGEST` | `false` | Phase 2 で `true` 化、PDF worker を起動 |
| `PAPER_QA_DAILY_SEARCH_LIMIT` | `30` | per-LINE-user 1 日上限 |
| `PAPER_QA_DAILY_QA_LIMIT` | `50` | per-LINE-user 1 日上限 (Phase 2+) |

---

## 5. Operational Concerns

### 5.1 Monitoring

- **Cloud Logging クエリ**:
    - `resource.type="cloud_run_revision" AND resource.labels.service_name="paper-qa-agent-service" AND severity>=WARNING`
    - 「retrieval source error」「ranking schema validation error」を grep
- **analytics-platform イベント**:
    - `business_event(action=paper_recommended)`: 1 検索 = 1 件
    - `business_event(action=summary_shown)`: ユーザが要約をタップした件数
    - `business_event(action=qa_answered)`: Phase 2+
    - `llm_call`: モデル別 / stage 別の input/output tokens、p50/p95 latency
    - `tool_invocation`: arxiv / semantic_scholar 別の成功率、p95 latency
- **正常時の指標**:
    - 検索 webhook → push 完了: p95 10 秒以内
    - ranking 一致率 (Sonnet top 5 ∩ Opus top 5) / 5: 0.6〜0.8
    - per-user daily 検索数: 中央値 3〜5

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| LINE 返信が来ない | (1) Cloud Tasks の queue 滞留を Console で確認、(2) agent-service の Cloud Logging で error 確認、(3) `PAPER_QA_ENABLED=false` のままになっていないか |
| 「処理中…」のまま 30 秒超 | Cloud Run cold start 疑い → `min-instances=1` を確認。Vertex AI 429 リトライ中の可能性 (`llm_call` 失敗ログを grep) |
| 検索結果がいつも同じような論文 | ranking の `recency_decay` が効いていない疑い。`papers.year DESC` の filter / weight を確認 |
| 「該当論文なし」が頻発 | (1) クエリが domain-out-of-scope の可能性 (例: 生物学を聞いた)、(2) source rate-limit 429 で結果 0 件、(3) embedding similarity 閾値が高すぎる |
| Cloud SQL CPU 100% 張り付き | (1) `driving-license-bot` または `fujisawa-platform` 側で重いクエリ実行中、(2) pgvector ivfflat の `lists` パラメータが不適切 → `lists = sqrt(N_rows)` で再構築 |
| ディスク満杯 | `papers` テーブルの古い `last_seen_at` を vacuum、または `driving-license-bot/terraform/variables.tf` の `cloudsql_disk_size_gb` を 20 に bump |
| ranking が壊れる (Sonnet が JSON を返さない) | Pydantic schema validation で即 retry → 3 回失敗で fallback ranking (rule_based 単独) |

### 5.3 Dependencies

| 依存 | 用途 |
|---|---|
| LINE Messaging API | webhook / push |
| Vertex AI (Claude Sonnet 4.6 / Opus 4.7) | Orchestrator / Ranking / Summarization / QA |
| Vertex AI (text-embedding-004) | クエリ・論文の埋め込み |
| Cloud SQL Postgres (`driving-license-bot` 共有 instance) | `paper_qa_db` + pgvector |
| Firestore | session / conversation / rate_limits |
| Cloud Tasks | 非同期ディスパッチ |
| Cloud Run | line-bot / agent-service / ingestion-worker (P2+) |
| GCS (Phase 2+) | PDF cache |
| arxiv API | 検索・abstract |
| Semantic Scholar Graph API | citation / authors |
| `security-platform` MCP Proxy | 全外部 MCP 呼出の中継 |
| `analytics-platform` | event JSONL → BigQuery |
| `paper-platform` (新規 path dep) | クロール / 正規化 / 埋め込み / ストア |

### 5.4 Non-Functional Requirements

#### 性能 (Performance)
- 応答時間目標:
    - LINE webhook 200 OK: 1 秒以内 (Cloud Tasks enqueue のみ)
    - 検索結果 Push 通知: p95 10 秒以内
    - QA 回答 Push 通知 (Phase 2+): p95 12 秒以内
    - PDF ingestion (Phase 2+): バックグラウンド、30〜60 秒許容
- スループット: 個人運営想定で 50 検索 / 50 QA per day がピーク
- 計算量: pgvector ivfflat top-k 検索は 100k 行で 100ms 以下

#### コスト (Cost)
- LLM 呼出 (per 1 検索):
    - Sonnet 4.6 (query refinement + 粗 ranking + summarization): ~5k input / 1.5k output tokens 合計 → 約 ¥4〜5
    - Opus 4.7 (精 ranking): ~5k input / 500 output → 約 ¥17
    - **1 検索あたり LLM ¥21〜25** (出展: Anthropic 公式 Vertex AI pricing、 概算)
- LLM 月額 (50 検索/日 × 30 日 = 1,500 検索 / 月): **¥30,000〜40,000**
- QA (Phase 2+): Opus 4.7 ~10k input / 1k output ≈ ¥80〜120 / 質問。 50 QA/日想定で **¥120,000〜180,000/月** (Phase 2 で再評価、 必要なら Sonnet fallback)
- ストレージ: 共有 Cloud SQL に 1GB 程度追加 (Phase 1)、Phase 2+ で PDF + section embedding = 5〜10GB
- Cloud Run: agent-service `min=1` で月額 ¥2,500、 line-bot `min=0` で ~¥100
- Cloud Tasks / Firestore / GCS: 合計 ¥500/月
- **月額合計 (Phase 1, 50 検索/日 想定)**: **¥33,000〜43,000** (LLM が支配的、 90% 占有)
- **コスト圧縮 lever** (`PAPER_QA_RANKING_USE_OPUS=false` で 単段 ranking): Opus 抜きで ¥10,000〜13,000/月に削減可能 (recall 低下とのトレードオフ)

> **要再評価**: 当初提案の月額 ¥5,500〜6,500 は LLM コストの集約を誤っていた (per-検索 ¥30-50 × 1500 = 大幅超過) ため上記に修正。 Phase 1 個人運営として ¥33k/月が許容範囲か、 検索 quota 削減 / Sonnet 単段への切替が必要かを Approval 前に判断。

#### プライバシー / データ保持
- PII 扱い: LINE userId は Firestore に保持。会話履歴 (`query` text) は analytics-platform に emit する際に raw のまま含める (個人運営のため自身のクエリのみ、家族共有 mode は Phase 5+)
- 保持期間:
    - Firestore `sessions`: 24 時間 TTL
    - Firestore `conversations`: 90 日
    - Firestore `rate_limits`: 3 日
    - 共有 Cloud SQL の `papers` / `paper_embeddings`: indefinite (公開論文メタデータのため PII なし)
    - GCS PDF cache: 30 日 (Phase 2+)
    - analytics-platform JSONL: analytics-platform 側のポリシーに準拠

#### キャパシティ
- 同時 LINE ユーザー: 5 まで (個人+家族想定)
- DB レコード: Phase 1 で `papers` 100k 行 / `paper_embeddings` 100k 行、Phase 2+ で `paper_sections` 1M 行を許容
- LINE Flex Message: 1 carousel = 5 bubble 固定、1 bubble 内のテキストは 200 chars 以内

---

## 6. Drawbacks

- **既存 `kanie-lab-agent` との機能重複**: kanie-lab も arxiv / Semantic Scholar 検索を持つ。ただし用途が異なる (kanie-lab = 入試準備の研究計画壁打ち / Web UI、本案 = LINE で会話的 paper Q&A)。Phase 4 で kanie-lab を `paper-platform` に移管する予定なので長期的な重複は解消される
- **Phase 1 で本文 RAG を持たない**: 「論文の中身を聞きたい」ニーズが満たされるのは Phase 2 以降。Phase 1 はメタデータ + 要約だけなので「Semantic Scholar を LINE で叩いてるだけでは？」という見方もできる。逆に Phase 1 のスコープが小さく 4〜6 週で動かせるのが利点
- **共有 Cloud SQL の SPOF 化**: `driving-license-bot` + `fujisawa-platform` + `paper-qa-agent` が同じ instance に乗ると、instance 障害時の影響範囲が広がる。Phase 4 で `paper-platform` への instance 切り出しを検討
- **個人運営の rate limit が将来のスケール時に重荷**: マルチユーザー化 (Phase 5) する際は Firestore rate_limits の集計コストが上がる。BigQuery 集計に切替が必要かも

## 7. Alternatives

### 案 A: 既存 `kanie-lab-agent` に LINE Bot フロントを足す
- 概要: kanie-lab の論文サーベイ機能をそのまま流用し、LINE webhook を追加する
- 却下理由: kanie-lab は (1) Web UI 前提の長文対話、(2) 研究計画の壁打ちが主目的で MCP 構成も SDGs / 法令系を含む過剰な装備。LINE の即応 (10 秒以内) には向かない。論文機能だけ切り出すと結局 `paper-platform` 相当が必要

### 案 B: `tech-news-agent` を会話 mode に拡張
- 概要: 既に arxiv crawler + LINE 配信を持つので push 型を pull 型に拡張する
- 却下理由: tech-news の crawler は「日次バッチ」前提でセッション概念がない。Cloud Tasks / Firestore session / hybrid retrieval を後付けすると ground-up 書き直しになる

### 案 C: ライブラリ化せず `paper-qa-agent` 単体に閉じる
- 概要: 本案の `paper-platform` を作らず `paper-qa-agent/app/sources/` 等に直接置く
- 却下理由: tech-news / kanie-lab に同等ロジックが既にあり、3 つ目を書くのは生産性が低い。`fujisawa-platform` の前例 (path dep ライブラリ) が機能している以上、同じパターンを踏襲するのが合理的

### 案 D: 検索を OpenAlex 単一ソースに絞る
- 概要: arxiv + Semantic Scholar を捨てて OpenAlex のみで Phase 1 を構築
- 却下理由: OpenAlex は citation 情報は強いが arxiv の最新 preprint が反映されるまで 1〜2 週ある。「最近の論文」を聞かれた時に取りこぼす

### 案 E: 専用 Cloud SQL instance を新設
- 概要: 共有 instance を使わず、`paper-qa-agent/terraform/cloudsql.tf` で `google_sql_database_instance` をフルに定義
- 却下理由: 月額 +¥1,500〜3,500 のコスト増 (db-f1-micro でも)。`fujisawa-platform` で確立した共有パターンが既にあり、運用負荷も大差ない

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-05-24 | Draft | 初稿 (Claude Code との設計セッション経由) |
