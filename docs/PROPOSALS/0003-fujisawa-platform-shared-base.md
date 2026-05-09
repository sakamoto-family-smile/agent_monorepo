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

```
                ┌──────────────────────────────────────────────────────┐
                │  Consumer Agents                                       │
                │  ┌──────────────────┐    ┌──────────────────────┐   │
                │  │ fujisawa-info-bot│    │ fujisawa-hokatsu-... │   │
                │  │ (Cloud Run、独立)│    │ (Cloud Run、独立)    │   │
                │  └────────┬─────────┘    └─────────┬────────────┘   │
                └───────────┼────────────────────────┼─────────────────┘
                            │ path dep                │ path dep
                            ▼                         ▼
                ┌──────────────────────────────────────────────────────┐
                │  fujisawa-platform/  (Python library, path dep)        │
                │                                                       │
                │  ┌──────────────────────────────────────────────────┐│
                │  │ crawler/                                         ││
                │  │   - polite_fetcher.py (UA / interval / IfMS)     ││
                │  │   - sitemap_loader.py (sitemap.xml + 1,100+ URL) ││
                │  │   - rss_poller.py (緊急情報 RSS、5 分間隔)       ││
                │  │   - wayback.py (CDX + web archive 経由 backfill) ││
                │  └──────────────────────────────────────────────────┘│
                │  ┌──────────────────────────────────────────────────┐│
                │  │ pdf_pipeline/                                    ││
                │  │   - docling_wrapper.py                           ││
                │  │   - hash_diff.py (SHA-256 比較で差分検知)        ││
                │  │   - freshness.py (as_of / source_url 自動付与)   ││
                │  └──────────────────────────────────────────────────┘│
                │  ┌──────────────────────────────────────────────────┐│
                │  │ knowledge_base/                                  ││
                │  │   - pgvector_store.py (Cloud SQL Postgres)       ││
                │  │   - embedding.py (Vertex text-embedding-004)     ││
                │  │   - search.py (cosine top-k + metadata filter)   ││
                │  └──────────────────────────────────────────────────┘│
                │  ┌──────────────────────────────────────────────────┐│
                │  │ models/                                          ││
                │  │   - facility.py (認可 / 認可外 / 藤沢型)         ││
                │  │   - vacancy_snapshot.py                          ││
                │  │   - admission_result.py                          ││
                │  │   - common.py (FreshnessMetadata 等)             ││
                │  └──────────────────────────────────────────────────┘│
                │  ┌──────────────────────────────────────────────────┐│
                │  │ resolver/                                        ││
                │  │   - facility_resolver.py (rapidfuzz + alias)     ││
                │  └──────────────────────────────────────────────────┘│
                │  ┌──────────────────────────────────────────────────┐│
                │  │ skills/  (動的注入される SKILL.md 群)            ││
                │  │   - citation_format.md                           ││
                │  │   - freshness_disclaimer.md                      ││
                │  │   - yasashii_nihongo.md (tsutaeru.cloud 誘導)    ││
                │  │   - escalate_to_municipal.md                     ││
                │  │   - line_output_format.md                        ││
                │  └──────────────────────────────────────────────────┘│
                └──────────────────────────────────────────────────────┘
                            │                         │
                            ▼                         ▼
                ┌──────────────────────────────────────────────────────┐
                │  Shared GCP Infrastructure                             │
                │   - Cloud SQL (driving-license-bot と instance 共有)  │
                │     ├─ DB: question_bank_db (driving-license-bot)    │
                │     ├─ DB: fujisawa_kb_db (本基盤、新規)              │
                │     └─ DB: hokatsu_db (保活、新規)                    │
                │   - Vertex AI text-embedding-004                       │
                │   - GCS: fujisawa-raw / fujisawa-pdf-archive (新規)   │
                │   - analytics-platform (path dep、observability)       │
                │   - security-platform (inventory.yaml に登録)          │
                └──────────────────────────────────────────────────────┘
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
│   └── skills/                            # SKILL.md 群、consumer から動的注入
│       ├── citation_format.md
│       ├── freshness_disclaimer.md
│       ├── yasashii_nihongo.md
│       ├── escalate_to_municipal.md
│       └── line_output_format.md
├── tests/
│   ├── crawler/
│   ├── pdf_pipeline/
│   ├── knowledge_base/
│   ├── resolver/
│   └── fixtures/
│       ├── sample_facility_list.html      # 認可・認可外の HTML サンプル
│       ├── sample_navi_extract.txt        # 申込ナビ PDF P19-20 抽出済テキスト
│       └── sample_r4_naiteisisuu.pdf       # Wayback で取得済の令和 4 年 PDF
└── Makefile
```

### 4.5 Test Plan

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

### 4.6 Migration / Rollback

- **Migration**: 新規モジュールのため migration なし。Cloud SQL に新 DB (`fujisawa_kb_db`) を作るだけ
- **Rollback**: 各 consumer から `fujisawa_platform` の import を外せば独立稼働に戻せる (既存 driving-license-bot は無影響)
- **既存ユーザー影響**: なし (新規)

### 4.7 Feature Enablement

env なし。consumer 側で `from fujisawa_platform import ...` するだけで利用可能。

ただし観測有効化のため:
- `FUJISAWA_PLATFORM_ANALYTICS_ENABLED=true` で analytics-platform への計装を ON
- 既定: ON

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
