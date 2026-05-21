# PROPOSAL-0003: 藤沢市データ共通基盤 `fujisawa-platform`

| | |
|---|---|
| **Status** | Draft |
| **Author** | @kurama554101 |
| **Created** | 2026-05-09 |
| **Updated** | 2026-05-09 |
| **Target** | cross-agent (`fujisawa-platform`、藤沢市情報 LINE Bot、保活エージェントが path dep で参照) |
| **Related PRs** | (none yet、本 PR が初版) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

藤沢市公式 HP / PDF を一次ソースとする 2 エージェント (LINE bot 0004 / 保活 0005) が共通で
依存する基盤を `fujisawa-platform/` に切り出し、**クロール / PDF 解析 / 鮮度メタデータ /
ベクトル検索 / 出典 Skill / 表記ゆれ吸収** を一元提供する。

両エージェントは独立 Cloud Run service として起動するが、データ取得層は path dep で
共通基盤を参照することで二重 fetch を排除し、Wayback バックフィルや ETL の運用も 1 箇所に集約する。

## 2. Motivation

### 現状の課題

両エージェント仕様書 (送信済 design) を読むと **データ取得層が完全に重複**している:

| 重複領域 | LINE bot 想定 | 保活想定 |
|---|---|---|
| クロール対象 | `city.fujisawa.kanagawa.jp` 全体 | `/hoiku/` 配下 + 申込ナビ PDF |
| クロール頻度 | 週次 | 月次 + 年次 |
| PDF 構造化 | (記載なし、想定 LangChain) | Docling |
| ベクトル検索 | Vertex AI Vector Search | Cloud SQL pgvector |
| 鮮度メタデータ | `as_of` 等 | `as_of` 等 |
| 出典 Skill | `citation-format/SKILL.md` | `citation_format` SKILL |
| 表記ゆれ吸収 | (該当なし) | FacilityResolver |

二重実装すると:
- city.fujisawa.kanagawa.jp に二重 fetch (技術的迷惑)
- ETL 失敗時の問い合わせ窓口がブレる
- ベクトル検索基盤が分裂 (Vertex Vector Search / pgvector の 2 系統)
- Skill File を両方でメンテ

### 放置するとどうなるか

- Wayback Machine からのバックフィル (proposal 0005 で重要、§A2 参照) の実装が両エージェントで重複
- 藤沢市保育課への一報 (法的整理) も 2 エージェント分の説明が要る
- 観測 (analytics-platform) で `service_name` が `fujisawa-info-bot` / `fujisawa-hokatsu-agent` に
  分かれた時、データソース層の責任がどちらにあるか追跡困難

### 2.1 Goals

- [ ] 両エージェントが path dep で参照可能な Python ライブラリ `fujisawa_platform` を提供
- [ ] 藤沢市 HP の polite crawler (UA 明示 / interval / If-Modified-Since / sitemap.xml 起点) を共通実装
- [ ] PDF 構造化パイプライン (Docling wrapper + hash 差分検知 + 鮮度メタデータ自動付与) を共通実装
- [ ] **Cloud SQL Postgres (driving-license-bot と instance 共有) + pgvector** をベクトル検索基盤として統一
- [ ] **Vertex AI `text-embedding-004` (768 次元)** を Embedding として統一 (driving-license-bot 既存パターン流用)
- [ ] 表記ゆれ吸収 `FacilityResolver` (rapidfuzz + alias dict + LLM fallback) を共通実装
- [ ] 出典 / 鮮度 / 免責 / やさしい日本語 (tsutaeru.cloud 誘導) などの **共通 Skill File 群**
- [ ] Wayback Machine 経由の過去データバックフィル helper (Phase 1 で実装、保活で先行利用)

### 2.2 Non-Goals

- 各エージェントの ドメインロジック (LINE bot のカテゴリ分類、保活の Score-Calc / Cost-Calc) は共通化しない
- LINE Webhook 受信層 (signature 検証 / Push) は別 proposal (`line-publisher` 共通モジュール、本 PR 範囲外)
  にする — 既存 `piyolog-analytics` LINE 基盤の再構成と一緒に扱うべき
- Vertex AI Vector Search の採用 (Cloud SQL pgvector に統一する判断、§7 案 B 参照)
- 藤沢市以外の自治体 (茅ヶ崎・横浜等) への対応 (将来検討、Phase 5+)
- multi-tenant / SaaS 化 (個人 / 家族用途のみ)

---

## 3. Proposal

### 3.1 User Stories

#### 3.1.1 ストーリー 1: LINE bot 開発者視点

> LINE bot を実装する際、藤沢市 HP のクロール / RSS / カテゴリページの fetch を自前で書かず、
> `from fujisawa_platform import crawler, knowledge_base` で済ませる。
> sitemap.xml を起点とした週次フルクロール / 緊急情報 RSS の 5 分間隔 poll は基盤が担う。
> 開発者は「この URL を読んで欲しい」「この種別の質問にはこの index を引く」だけ書く。

#### 3.1.2 ストーリー 2: 保活エージェント開発者視点

> 保活エージェントを実装する際、申込ナビ PDF (47 ページ・14 MB) の Docling パース、
> Wayback Machine からの過去 PDF バックフィル (`r4-4nyuusyonaiteisisuu.pdf` 等)、
> 認可施設一覧 HTML からの 128 施設抽出を自前で書かず、`fujisawa_platform.pdf_pipeline` /
> `fujisawa_platform.wayback` / `fujisawa_platform.facility_resolver` を呼ぶ。
> ドメインロジック (Score-Calc / Cost-Calc / Strategy) に集中できる。

### 3.2 Notes / Constraints / Caveats

調査結果 ([`notes/fujisawa-platform-investigation-2026-05-09.md`](notes/fujisawa-platform-investigation-2026-05-09.md)) からの前提:

- **robots.txt は不在 (HTTP 404)**: デフォルト解釈で全許可だが、礼儀ルール (UA 明示 / 同時接続 1 / interval 3s 以上 / 深夜帯バッチ) を必ず徹底
- **sitemap.xml は約 1,100+ URL**: LINE bot のクロール起点として実用的、`<lastmod>` 不在のため `Last-Modified` ヘッダで個別判定
- **過去 PDF の URL パターンが 2 世代**: `hoiku/documents/` (2024 以前) と `documents/16736/` (2025 以降) の両方に対応する fetcher が必要
- **Wayback Machine からのバックフィルが技術的に可能**: `web.archive.org/web/<timestamp>/<original_url>` への curl 直撃で取得可、CDX API は 503 が散発するため retry 必須
- **令和 4 年 (2022) の `r4-4nyuusyonaiteisisuu.pdf` は最低内定指数を完全公表していたが、令和 5 年以降は公表停止**: バックフィル範囲を「令和 4 年は専用パーサ」「令和 5-7 年は申込/空き状況のみ」と分岐
- **多言語 (やさしい日本語 / 英語) は `tsutaeru.cloud` 経由の独自翻訳ページ**が藤沢市側に既存。LINE bot 側で再実装するより誘導が現実的
- **緊急情報 RSS が存在**: LINE bot Phase 4 (緊急情報プッシュ) の入力源として直接 poll 可能
- **法的整理**: 事実情報 (施設名 / 住所 / 電話 / 定員) の抽出は OK、解説文章は引用要件遵守、運用前に保育課 / 広報課への一報が **Pre-launch checklist** で必須
- **個人プロジェクト規模**: 月 100 ユーザー想定、Cloud SQL は driving-license-bot と instance 共有 (DB 分離) で月 ¥0 増で済む

### 3.3 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| 藤沢市 HP の構造変更で全 ETL が壊れる | High | 各 ETL に hash 差分検知 + 期待スキーマ検証を入れ、Slack 通知で早期発見 |
| Wayback Machine の rate limit / 503 | Medium | 5 秒間隔 + tenacity の指数バックオフ、503 持続時は手動再開で OK (バックフィルは 1 度きり) |
| Cloud SQL instance 共有による相互影響 | Medium | DB 分離 (`fujisawa_platform` DB) + connection pool 上限を per-app で設定。本格運用で問題が出たら instance 分離 |
| `text-embedding-004` 終了 | Low | embedding モデルは Protocol で抽象化、移行時は再 indexing (driving-license-bot と同パターン) |
| 藤沢市から「クロール停止して」の連絡 | Low | 連絡先 (`fujisawa-platform-contact@example.com` 等) を UA に明記、即対応可能体制 |
| 個人情報 (LINE userId / 世帯収入) の混入 | Low | `fujisawa_platform` は public 情報のみ扱う設計、ユーザー固有データは consumer 側 (LINE bot / 保活) の責任 |
| Docling のメジャー更新で出力 schema 変化 | Low | version pin + 出力検証ロジックで吸収 |

---

## 4. Design Details

### 4.1 アーキテクチャ概略

`fujisawa-platform` は **Python ライブラリ (path dep)** であり独立した Cloud Run service を
**持たない**。消費者エージェント (LINE bot / 保活) は in-process で import し、
ライブラリ内の関数経由で Cloud SQL に **直接** asyncpg 接続する。
データの**書き込み**は別途 Cloud Run Jobs (バッチ ETL) が一手に担い、
消費者エージェントは **読み取り専用**。

詳細なアクセス経路 / ETL の責任分離は §4.5 を参照。

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Read-Only Path (アプリケーション)                                         │
│                                                                          │
│  ┌──────────────────┐                ┌──────────────────────┐          │
│  │ fujisawa-info-bot│                │ fujisawa-hokatsu-... │          │
│  │ (Cloud Run、独立)│                │ (Cloud Run、独立)    │          │
│  └────────┬─────────┘                └─────────┬────────────┘          │
│           │ from fujisawa_platform import ...   │                        │
│           │ (path dep、in-process)               │                        │
│           ▼                                     ▼                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ fujisawa-platform/  (Python library)                              │  │
│  │                                                                   │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐             │  │
│  │  │ crawler/     │ │ pdf_pipeline/│ │ knowledge_   │             │  │
│  │  │ (polite_     │ │ (docling /   │ │ base/        │             │  │
│  │  │  fetcher /   │ │  hash_diff / │ │ (pgvector_   │             │  │
│  │  │  sitemap /   │ │  freshness)  │ │  store /     │             │  │
│  │  │  rss /       │ │              │ │  embedding / │             │  │
│  │  │  wayback)    │ │              │ │  search)     │             │  │
│  │  └──────────────┘ └──────────────┘ └──────┬───────┘             │  │
│  │                                            │                       │  │
│  │  ┌──────────────┐ ┌──────────────┐         │                       │  │
│  │  │ resolver/    │ │ models/      │         │                       │  │
│  │  │ (facility_   │ │ (Pydantic    │         │                       │  │
│  │  │  resolver)   │ │  schema)     │         │                       │  │
│  │  └──────────────┘ └──────────────┘         │                       │  │
│  │                                            │                       │  │
│  │  ┌─────────────────────────────────────────┘                       │  │
│  │  │ asyncpg pool (per-app)                                          │  │
│  │  ▼                                                                  │  │
│  │  skills/  (SKILL.md 群、consumer から動的注入)                    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│           │                                                              │
└───────────┼──────────────────────────────────────────────────────────────┘
            │ SELECT (読み取り専用)
            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Cloud SQL Postgres (driving-license-bot と instance 共有、DB 分離)       │
│   - DB: question_bank_db   (driving-license-bot)                         │
│   - DB: fujisawa_kb_db     (本基盤、新規)                                │
│   - DB: hokatsu_db         (保活、新規)                                   │
│                                                                          │
│   pgvector / facilities / pages / pdf_documents /                        │
│   vacancy_snapshots / application_snapshots /                            │
│   admission_results / competition_stats                                  │
└──────────────────────────────────────────────────────────────────────────┘
            ▲
            │ INSERT/UPSERT (書き込みは ETL のみ)
            │
┌──────────────────────────────────────────────────────────────────────────┐
│ Write Path (バッチ ETL、§4.5 参照)                                        │
│                                                                          │
│  Cloud Scheduler ──▶ Cloud Run Jobs (fujisawa-platform/etl/ 配下)        │
│   - weekly_crawl_etl       (週次、sitemap.xml ~7,900 URL を差分 crawl)    │
│   - monthly_vacancy_etl    (月次 22 日、空き / 申込状況 PDF)             │
│   - monthly_stats_compute  (月次 23 日、competition_stats 集計)          │
│   - half_yearly_facility_etl (半年次、施設一覧 HTML)                     │
│   - yearly_navi_etl        (年次、申込ナビ PDF 47 ページ)                │
│   - biyearly_admission_etl (年 2 回、4月入所結果 PDF)                    │
│   - wayback_backfill       (一度きり、令和 4-6 年データ)                 │
│                                                                          │
│   各 Job は fujisawa_platform.crawler / pdf_pipeline / knowledge_base    │
│   を呼び出して fetch → 構造化 → embedding → DB UPSERT                    │
└──────────────────────────────────────────────────────────────────────────┘

その他 共有 GCP 資源:
   - Vertex AI text-embedding-004
   - GCS: fujisawa-raw / fujisawa-pdf-archive (PDF 一次保存 + Wayback バックアップ)
   - analytics-platform (path dep、observability)
   - security-platform (inventory.yaml に登録、proxy 経由でクロール)
```

### 4.2 データモデル

新規 Pydantic models (path dep で両エージェントから import):

```python
# fujisawa_platform/models/common.py
@dataclass(frozen=True)
class FreshnessMetadata:
    as_of: datetime          # 取得日時 (UTC)
    source_url: str
    source_pdf_url: str | None = None
    snapshot_date: date | None = None  # PDF 発行日 (あれば)
    etl_job_id: str | None = None
    schema_version: str = "v1"

# fujisawa_platform/models/facility.py
@dataclass(frozen=True)
class Facility:
    facility_id: str           # FacilityResolver 経由で正規化
    name: str
    facility_type: Literal[
        "公立保育所", "法人等保育所", "認定こども園", "小規模保育事業",
        "家庭的保育事業", "藤沢型A", "藤沢型B", "藤沢型C",
        "企業主導型", "認可外その他",
    ]
    address: str
    phone: str | None = None
    capacity: int | None = None
    nearest_station: str | None = None
    walk_minutes: int | None = None
    official_url: str | None = None
    aliases: list[str] = field(default_factory=list)  # 表記ゆれ
    freshness: FreshnessMetadata
```

詳細は実装 PR (Phase 1) で確定。

### 4.3 Cloud SQL スキーマ追加 (新規 DB)

driving-license-bot 既存 instance に DB を追加:

```sql
-- DB: fujisawa_kb_db
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE pages (
    page_id      TEXT PRIMARY KEY,           -- url の hash
    url          TEXT NOT NULL,
    title        TEXT,
    content      TEXT NOT NULL,
    embedding    vector(768) NOT NULL,
    category     TEXT,                       -- 防災 / 子育て / ゴミ等
    fetched_at   TIMESTAMPTZ NOT NULL,
    last_modified TIMESTAMPTZ,                -- HTTP Last-Modified
    schema_version TEXT NOT NULL DEFAULT 'v1'
);
CREATE INDEX pages_embedding_ivfflat ON pages
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX pages_category_idx ON pages (category);
CREATE INDEX pages_fetched_at_idx ON pages (fetched_at);

CREATE TABLE pdf_documents (
    pdf_id       TEXT PRIMARY KEY,           -- url の hash
    url          TEXT NOT NULL,
    chunk_index  INTEGER NOT NULL,           -- Docling chunk 単位
    chunk_text   TEXT NOT NULL,
    embedding    vector(768) NOT NULL,
    page_number  INTEGER,
    fetched_at   TIMESTAMPTZ NOT NULL,
    pdf_hash     TEXT NOT NULL,              -- SHA-256
    schema_version TEXT NOT NULL DEFAULT 'v1'
);
CREATE INDEX pdf_documents_embedding_ivfflat ON pdf_documents
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX pdf_documents_pdf_hash_idx ON pdf_documents (pdf_hash);
```

保活 / LINE bot 各エージェントは別 DB (`hokatsu_db` / `fujisawa_info_bot_db`) を持ち、
ユーザー固有データはそこに格納する (本基盤は public 情報のみ)。

### 4.4 主要モジュール

```
fujisawa-platform/
├── pyproject.toml                         # uv project, optional [pgvector] extras
├── README.md                              # README_TEMPLATE 準拠
├── docs/
│   └── DESIGN.md                          # SYSTEM_DESIGN_TEMPLATE 準拠
├── fujisawa_platform/
│   ├── __init__.py
│   ├── config.py                          # pydantic-settings
│   ├── crawler/
│   │   ├── polite_fetcher.py              # requests + If-Modified-Since + UA
│   │   ├── sitemap_loader.py              # sitemap.xml parser
│   │   ├── rss_poller.py                  # 緊急情報 RSS
│   │   └── wayback.py                     # CDX + web archive backfill
│   ├── pdf_pipeline/
│   │   ├── docling_wrapper.py             # Docling × hash diff
│   │   ├── hash_diff.py
│   │   └── freshness.py                   # as_of/source_url 自動付与
│   ├── knowledge_base/
│   │   ├── pgvector_store.py              # asyncpg + pgvector (driving-license-bot パターン流用)
│   │   ├── embedding.py                   # VertexEmbeddingClient + MockEmbeddingClient
│   │   └── search.py                      # top-k cosine + metadata filter
│   ├── models/
│   │   ├── common.py                      # FreshnessMetadata
│   │   ├── facility.py
│   │   ├── vacancy_snapshot.py
│   │   └── admission_result.py
│   ├── resolver/
│   │   └── facility_resolver.py           # rapidfuzz + alias + LLM fallback
│   ├── skills/                            # SKILL.md 群、consumer から動的注入
│   │   ├── citation_format.md
│   │   ├── freshness_disclaimer.md
│   │   ├── yasashii_nihongo.md
│   │   ├── escalate_to_municipal.md
│   │   └── line_output_format.md
│   └── etl/                               # Cloud Run Jobs entry points (§4.5)
│       ├── weekly_crawl.py                # sitemap.xml 全クロール
│       ├── monthly_vacancy.py             # 空き状況 + 申込状況 PDF
│       ├── monthly_stats_compute.py       # competition_stats 集計
│       ├── half_yearly_facility.py        # 認可・認可外施設一覧 HTML
│       ├── yearly_navi.py                 # 申込ナビ PDF
│       ├── biyearly_admission.py          # 4 月入所結果 PDF
│       └── wayback_backfill.py            # 令和 4-6 年データ (一度きり)
├── tests/
│   ├── crawler/
│   ├── pdf_pipeline/
│   ├── knowledge_base/
│   ├── resolver/
│   ├── etl/                               # 各 Job の dry-run + idempotency テスト
│   └── fixtures/
│       ├── sample_facility_list.html      # 認可・認可外の HTML サンプル
│       ├── sample_navi_extract.txt        # 申込ナビ PDF P19-20 抽出済テキスト
│       └── sample_r4_naiteisisuu.pdf       # Wayback で取得済の令和 4 年 PDF
└── Makefile
```

### 4.5 アクセス経路と ETL 投入タイミング

#### 4.5.1 アクセス経路: path dep ライブラリ → Cloud SQL 直接接続

両エージェントは `fujisawa-platform` を **Python ライブラリ (path dep)** として import し、
ライブラリ内の関数経由で Cloud SQL に **直接 asyncpg 接続** する。HTTP / REST / MCP の
hop は介在しない。

```python
# 消費者エージェント (info-bot / 保活) のコード例
from fujisawa_platform.knowledge_base import search
from fujisawa_platform.resolver import resolve_facility

# in-process 呼出 → asyncpg pool 経由で Cloud SQL に直撃
results = await search(query="鵠沼地区のゴミの日", top_k=5)
facility = await resolve_facility("藤沢保育園")
```

```toml
# 消費者側の pyproject.toml
[project]
dependencies = ["fujisawa-platform"]

[tool.uv.sources]
fujisawa-platform = { path = "../fujisawa-platform" }
```

#### 4.5.2 なぜ DB 直接 (path dep) か (案 C で API 化を却下した理由)

| 観点 | DB 直接 (採用) | API 化 (§7 案 C で却下) |
|---|---|---|
| latency | in-process + asyncpg = 数 ms | Cloud Run hop で 50-200ms |
| コールドスタート | 各 Cloud Run のみ (1 段) | プラットフォーム側でも発生 (2 段) |
| 可動部品 | Cloud SQL + 2 Cloud Run | Cloud SQL + 3 Cloud Run + IAM |
| schema 変更 | path dep の version 上げで全消費者に伝搬、テストで検出 | 後方互換 API バージョニング必須 |
| Phase 5+ 外部公開時 | 後付けで API を被せる余地あり | — |

#### 4.5.3 読み取り / 書き込みの責任分離

- **消費者エージェント (info-bot / 保活)**: **読み取り専用** (`SELECT` のみ)、書き込みは禁止
- **書き込みは ETL Cloud Run Jobs のみ** (`fujisawa_platform/etl/` 配下、Cloud Scheduler でトリガ)
- IAM 上も DB ロールを分離: `consumer_role` (SELECT のみ) / `etl_role` (INSERT / UPSERT / DELETE)

#### 4.5.4 ETL 投入タイミング (Cloud Run Jobs)

`fujisawa_platform/etl/` 配下に **6 種類の定期 Job + 1 種類の一度きり Job** を配置。
すべて Cloud Scheduler でトリガし、深夜帯 (03:00 JST) に集中させて藤沢市 HP の負荷を避ける。

| Job 名 | 頻度 / トリガ | 取得対象 | 書き込み先テーブル | 主な利用先 |
|---|---|---|---|---|
| `weekly_crawl_etl` | 毎週日曜 03:00 JST | `sitemap.xml` の URL (実測 7,906 件 @ 2026-05) を **差分 crawl** (HEAD で Last-Modified 比較 → 更新有り URL のみ GET、 通常週次は数百件) | `pages` (HTML 本文 + embedding) | LINE bot (0004) RAG |
| `monthly_vacancy_etl` | 毎月 22 日 03:00 JST | 空き状況 / 申込状況 PDF (Docling 構造化) | `vacancy_snapshots`, `application_snapshots` | 保活 (0005) VacancyAgent |
| `monthly_stats_compute` | 毎月 23 日 03:00 JST | 過去 3 年分のスナップショット集計 (外部 fetch なし) | `competition_stats` | 保活 StrategyAgent |
| `half_yearly_facility_etl` | 4 月・10 月 1 日 03:00 JST | 認可・認可外施設一覧 HTML (`pandas.read_html` + BeautifulSoup でリンク URL 抽出) | `facilities` (160 件) | 保活 SearchAgent |
| `yearly_navi_etl` | 4 月・10 月 1 日 03:00 JST | 申込ナビ PDF (47 ページ、14 MB) を Docling で構造化 + 解説文章 chunk 化 | `pdf_documents` (Q&A RAG)、`rules/reiwa{N}/*.yaml` は別経路で手動更新 | 保活 QAAgent + Score-Calc DSL |
| `biyearly_admission_etl` | 2 月・3 月の指定日 | 4 月入所結果 PDF (1 次・2 次) | `admission_results` | 保活 StrategyAgent (履歴) |
| `wayback_backfill` | **一度きり (Phase 0)** | Wayback CDX → 令和 4-6 年の年次入所結果 PDF + `r4-4nyuusyonaiteisisuu.pdf` | `admission_results` (令和 4-6 年) + `competition_stats.historical_minimum_index_2022` | 保活 Plan MCP のハイブリッドモデル |

**例外: 緊急情報 RSS は LINE bot (0004) 専用**

緊急情報 RSS の 5 分間隔 poll は `fujisawa-info-bot/batch/poll_rss.py` 側に実装する
(共通 DB に格納する必然性が薄い、保活では使わない、5 分間隔の job が他消費者にも見えると
混乱する、という理由)。LINE bot 独自の Firestore (`emergency_seen/{guid}`) で重複検知。

#### 4.5.5 投入時の整合性 (consumer が partial state を読まないように)

ETL の実行中に消費者エージェントが SELECT すると中間状態を読む可能性がある。対策:

- **`vacancy_snapshots` / `admission_results`**: `(year_month / year, round)` で行を分離し、
  既存月分が確定してから次月分を UPSERT。`WHERE year_month = '2026-01'` の一貫性は
  partial insert 中でも保たれる
- **`pages`** (週次フルクロール): `version` カラムを追加し、ETL は新 version で `INSERT`、
  完了後に view の `WHERE version = $latest` を切り替える blue-green 方式 (Phase 6 で実装、
  それまでは「古い行が混在」を許容)
- **`facilities`** (半年次、頻度低): **UPSERT + 条件付き DELETE** を 1 トランザクションで。
  - `INSERT ... ON CONFLICT (facility_id) DO UPDATE SET ...` で incoming を UPSERT
  - `incoming` に無く、 下流 4 テーブル (`admission_results` / `vacancy_snapshots` /
    `application_snapshots` / `competition_stats`) からも参照されていない facility
    のみ DELETE
  - 旧設計 (一律 DELETE → INSERT) は FK 参照を持つ admission_results 等が登場した
    時点で `ForeignKeyViolationError` で fail する (2026-05-18 実 GCP 検証で発覚)。
    facility_id は `slugify_facility_id(type, name)` で stable hash なため UPSERT
    で十分という方針に修正
  - 消費者側は SELECT 失敗 → tenacity retry で吸収 (atomicity は変わらず維持)

#### 4.5.6 ETL 失敗時の handling

- 各 Job は `etl_runs/{job_name}/{date}` に取得 URL の SHA-256 を記録、前回と同じなら処理スキップ
- 期待スキーマと違う場合 (列名変更 / 件数の急減 / null 率上昇) は Slack/LINE 通知
- 旧データは温存 (失敗中も応答可能、ただし `freshness.as_of` の経過日数で UI に「N 日前のデータ」と注記)
- 5 連敗で fail-fast、再開は手動

### 4.6 Test Plan

- **Unit**:
  - `polite_fetcher`: User-Agent / interval / If-Modified-Since の挙動 (mock サーバ)
  - `sitemap_loader`: 1,100+ URL の parse 精度、`<lastmod>` 不在時のフォールバック
  - `wayback`: CDX 503 → retry / 該当無し時の handling
  - `docling_wrapper`: 申込ナビ PDF P19-P20 抽出が ground truth (B 優先順位 10 階層 / A-1 = 20) と一致
  - `facility_resolver`: 「藤沢保育園」「藤沢市立藤沢保育園」「キディ鵠沼・藤沢」「キディ鵠沼藤沢」が同 ID に解決される
  - `pgvector_store`: in-memory テストは MockEmbeddingClient で deterministic
- **Integration**:
  - 実 Cloud SQL (Workload Identity 経由) への connect / search smoke (CI で回す)
  - 実 Vertex `text-embedding-004` 呼出 smoke (CI で回す、5 ベクトルのみ)
- **Manual / E2E**:
  - [ ] 藤沢市 HP の主要 5 ページに対して polite crawler を回し、レスポンスタイム / Last-Modified を観察
  - [ ] Wayback から `r4-4nyuusyonaiteisisuu.pdf` 取得 → Docling 抽出 → 120+ 施設の指数表が parse できる
  - [ ] consumer 側 (LINE bot 開発者の立場) で `from fujisawa_platform import knowledge_base` が動作

### 4.7 Migration / Rollback

- **Migration**: 新規モジュールのため migration なし。Cloud SQL に新 DB (`fujisawa_kb_db`) を作るだけ
- **Rollback**: 各 consumer から `fujisawa_platform` の import を外せば独立稼働に戻せる (既存 driving-license-bot は無影響)
- **既存ユーザー影響**: なし (新規)

### 4.8 Feature Enablement

env なし。consumer 側で `from fujisawa_platform import ...` するだけで利用可能。

ただし観測有効化のため:
- `FUJISAWA_PLATFORM_ANALYTICS_ENABLED=true` で analytics-platform への計装を ON
- 既定: ON

各 ETL Job も env で無効化可能:
- `FUJISAWA_ETL_<JOB_NAME>_ENABLED=false` で Cloud Scheduler のトリガをスキップ (Phase 0 で個別 Job を段階的に有効化するため)

---

## 5. Operational Concerns

### 5.1 Monitoring

- analytics-platform に計装 (`service_name="fujisawa-platform"`)
- 重要メトリクス:
  - `crawler.fetch_count` (URL ごとの fetch 回数)
  - `crawler.cache_hit_ratio` (If-Modified-Since 304 の比率)
  - `wayback.backfill_failures`
  - `pdf_pipeline.docling_duration_ms`
  - `knowledge_base.search_latency_p95`
- アラート: Cloud Monitoring で `crawler.fetch_count` が想定上限 (時間あたり 50 fetch) を超えたら通知

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| 藤沢市 HP の応答が遅い (5xx 連発) | polite fetcher のリトライ間隔を倍に、ETL 一時停止、藤沢市側へ確認連絡 |
| Wayback CDX が 503 を返す | 5 秒待って retry、5 連敗で fail-fast、再開は手動 |
| Docling の出力が前回と違う | hash 差分検知で alarm → 出力サンプルを目視確認 → schema_version をインクリメント |
| pgvector の検索結果が空 | embedding 次元 (768) の不整合か index 未作成。`init_schema.py` で再構築 |
| FacilityResolver が誤マッチ | `aliases` テーブルに正解を追加、rapidfuzz threshold 調整、LLM fallback の prompt 調整 |

### 5.3 Dependencies

- **新規**:
  - `requests` / `httpx` (HTTP client、polite fetcher)
  - `lxml` / `beautifulsoup4` (HTML parse)
  - `docling` (PDF 構造化)
  - `pandas` (`read_html` 用)
  - `rapidfuzz` (FacilityResolver fuzzy match)
  - `asyncpg` + `pgvector` (Postgres + ベクトル拡張)
  - `tenacity` (retry)
  - `pydantic` v2 + `pydantic-settings`
- **既存利用**:
  - `analytics-platform` (path dep、計装)
  - driving-license-bot の `embedding.py` パターン (実装参考)
- **GCP サービス**:
  - Cloud SQL (driving-license-bot 既存 instance 共有)
  - Vertex AI Embedding API
  - GCS (`fujisawa-raw` / `fujisawa-pdf-archive`)
  - Workload Identity (キーレス認証)

### 5.4 Non-Functional Requirements

#### 性能
- crawler: polite mode で 1 URL/3 秒、sitemap 全クロール 1,100 URL = 約 1 時間
- PDF 構造化: 申込ナビ 47 ページ = 30〜60 秒
- pgvector 検索: top-10 で p95 < 200ms (既存 driving-license-bot 同等)

#### コスト
- Cloud SQL: driving-license-bot と instance 共有のため **¥0 増**
- Vertex Embedding: 1 回呼出 ≈ ¥0.0008 (768 次元)。1,100 URL × 月 4 回 = ¥3.5/月、PDF chunk 約 200 個 × 月 1 回 = ¥0.2/月。**月 ¥10 以下**
- GCS (raw + pdf archive): 月 100 MB 以下、**月 ¥10 以下**
- 合計: **月 ¥30 以下** (既存リソース共有のため)

#### プライバシー / データ保持
- 本基盤は **public 情報のみ** 扱う (個人情報は consumer 側の責任)
- `pages` / `pdf_documents` テーブルは永続。ただし `fetched_at` から 1 年経過したら GCS に export して DB から削除 (cron)

#### キャパシティ
- pages: 5,000 行上限 (sitemap 1,100 URL × バージョン履歴 4 で十分)
- pdf_documents: 10,000 行上限 (PDF 200 個 × chunk 平均 50)

---

## 6. Drawbacks

- **2 エージェント開発が共通基盤の安定化を待つ**: 0003 が固まる前に 0004 / 0005 を始められない (ただし基盤は最小機能から始めれば 1〜2 週で回せる)
- **Cloud SQL instance 共有のリスク**: driving-license-bot に影響が出る可能性。本格運用で問題が顕在化したら instance 分離 (DB を移すだけ)
- **fujisawa-platform 単体での価値が薄い**: 横展開先 (横浜市・茅ヶ崎市) が無いと基盤の汎用性は活きない
- **Wayback Machine 依存**: 過去データバックフィルが Wayback の生存に依存。Internet Archive が消えると過去倍率データが取れない (ただしこれは保活側のリスクで、基盤は生データを取れたものを保持するだけ)

これらを踏まえても、二重 fetch 排除と運用集約のメリットが上回ると判断。

## 7. Alternatives

### 案 A: 共通基盤を作らず、各エージェントが独自実装

- **概要**: LINE bot / 保活 がそれぞれクロール・PDF 処理・ベクトル検索を独自実装
- **却下理由**:
  - city.fujisawa.kanagawa.jp に二重 fetch (技術的迷惑、市側に問い合わせが来る可能性)
  - 同じバグを 2 回直す
  - 観測の `service_name` が分裂し、データ層の責任が追跡困難
  - Wayback バックフィルを 2 回書く必要

### 案 B: Cloud SQL pgvector ではなく Vertex AI Vector Search を採用

- **概要**: ベクトル検索に Vertex AI Vector Search (managed) を使う
- **却下理由**:
  - 最小 endpoint で月 ¥10,000+ 発生 (個人プロジェクト規模に過剰)
  - driving-license-bot が pgvector パターンを既に持っており、流用が早い
  - pgvector は instance 共有で月 ¥0 増、Cloud SQL の運用は既に習熟
  - 規模が 10,000 ベクトル超になったら再評価 (現状は 5,000 以下想定)

### 案 C: 共通基盤を Cloud Run service として独立稼働 (REST API or MCP)

- **概要**: `fujisawa-platform` を Cloud Run で起動し、LINE bot / 保活 が REST or MCP で呼ぶ
- **却下理由**:
  - latency が増える (path dep ライブラリなら in-process)
  - Cloud Run instance のコールドスタート問題
  - 可動部品が増え運用負荷増
  - Phase 5+ で複数 agent が読みたくなったら再検討する余地はある

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-05-09 | Draft | 初稿 (本 PR) |
| 2026-05-09 | Draft 改訂 | レビュー回答を反映: §4.1 アーキ図に Read-Only Path / Write Path の分離を明記、§4.5 を新設 (アクセス経路と ETL 投入タイミングを詳細化)、§4.4 に `etl/` ディレクトリ追加、§4.8 に ETL 個別有効化 env を追加 |
| 2026-05-18 | 設計修正 | §4.5.5 の `facilities` 投入戦略を「全削除 → 全 INSERT」から「UPSERT + 条件付き DELETE」に変更。 旧設計は admission_results 等の FK 参照が登場すると `ForeignKeyViolationError` で fail することが実 GCP 検証で発覚 (R4 backfill 178 行 → half_yearly_facility 再実行時)。 facility_id が `slugify_facility_id` で stable hash 化済のため UPSERT で十分。 incoming に無く下流参照も無い orphan のみ DELETE して陳腐化対応。 atomicity 維持 (1 トランザクション) は変わらず。 |
| 2026-05-21 | 設計修正 | §4.5.4 の `weekly_crawl_etl` を「全件 GET」から「HEAD で Last-Modified 比較 → 差分 GET」 方式に変更。 旧設計の sitemap URL 数想定 (1,100+) は実測 7,906 件で 7 倍規模、 全件 3 秒/URL polite rate だと 6.6 時間必要で task timeout 90 分内に完走不能だった (2026-05-16 自動実行が 1,797 URL 処理時点で timeout)。 新方式は HEAD (0.5 秒/URL × 7,906 = 66 分) で更新検知 → 数百件の GET だけ実施。 task timeout は 28,800 秒 (8 時間) に拡張 (初回 full crawl 用)。 `_runner.py` に orphan `running` レコードの reclassify (`abort_stale_running`) も同 PR で追加。 派生 backlog: `docs/PROPOSALS/notes/fujisawa-info-bot-follow-up-2026-05-21.md` 項目 G。 |
