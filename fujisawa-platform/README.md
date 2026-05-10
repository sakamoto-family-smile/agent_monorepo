# fujisawa-platform

藤沢市 HP / PDF を一次ソースとする共通基盤ライブラリ。両エージェント
(`fujisawa-info-bot` / `fujisawa-hokatsu-agent`) が path dep で参照し、
**クロール / PDF 解析 / ベクトル検索 / 出典 Skill / 表記ゆれ吸収 / ETL** を一元提供する。

> **Status**: Phase 3 実装済 (Phase 1-2 完了 + crawler/rss_poller + crawler/wayback)

設計詳細は [`../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md`](../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md) 参照。
本 README は「動かす / 取り込む」観点に絞る。

---

## 0. Quickstart

### 0.1 前提

| ツール | バージョン | 備考 |
|---|---|---|
| Python | 3.12+ | `pyproject.toml` で指定 |
| uv | 最新 | パッケージ管理 |
| Cloud SQL (Postgres) + pgvector | optional | 本番ベクトル検索を回す場合のみ |

### 0.2 セットアップ

```bash
cd agent_monorepo/fujisawa-platform

make install            # 基本依存 (resolver 含む)
make install-pgvector   # + asyncpg + pgvector (Phase 4 ETL 時)
make install-vertex     # + google-cloud-aiplatform (本番 embedding)
make install-pdf        # + docling (PDF 構造化、ETL Job のみ)
make install-all        # 全 optional 含む
```

### 0.3 テスト・静的解析

```bash
make test             # pytest
make lint             # ruff check
make format           # ruff format + auto-fix
make check            # lint + test
```

### 0.4 consumer (LINE bot / 保活) からの利用

```toml
# 消費者エージェントの pyproject.toml
[project]
dependencies = ["fujisawa-platform"]

[tool.uv.sources]
fujisawa-platform = { path = "../fujisawa-platform" }
```

```python
# 消費者コード例
from fujisawa_platform.crawler import (
    PoliteFetcher,
    PoliteFetcherConfig,
    WaybackClient,
    WaybackConfig,
    parse_feed,
    parse_sitemap,
)
from fujisawa_platform.models import FreshnessMetadata
from fujisawa_platform.skills import get_skill
from fujisawa_platform.resolver import FacilityResolver, ResolverEntry
from fujisawa_platform.knowledge_base import (
    InMemoryStore,
    MockEmbeddingClient,
    PageDocument,
)
from fujisawa_platform.pdf_pipeline import build_freshness, compute_hash, has_changed

# (1) polite な fetch
config = PoliteFetcherConfig(
    user_agent="my-app/0.1 (https://example.com/contact)",
    min_interval_sec=3.0,
)
async with PoliteFetcher(config) as fetcher:
    result = await fetcher.fetch("https://www.city.fujisawa.kanagawa.jp/sitemap.xml")
    if hasattr(result, "text"):
        entries = parse_sitemap(result.text.encode("utf-8"))
        print(f"Found {len(entries)} URLs in sitemap")

# (2) 表記ゆれ吸収
resolver = FacilityResolver([
    ResolverEntry(facility_id="fuji-001", canonical_name="藤沢保育園", aliases=[]),
])
hit = resolver.resolve("藤沢保育園")  # canonical match → score 1.0

# (3) ベクトル検索 (テストは Mock、本番は Vertex)
embedder = MockEmbeddingClient()  # or VertexEmbeddingClient(project_id=...)
store = InMemoryStore()           # or PgvectorStore(...) (Phase 4 で実装)
await store.upsert_page(PageDocument(
    page_id="page-1",
    url="https://www.city.fujisawa.kanagawa.jp/...",
    content="...",
    embedding=embedder.embed("..."),
    fetched_at=datetime.now(UTC),
))
hits = await store.search_pages(embedder.embed("query"), top_k=5)

# (4) PDF パイプライン (差分検知 + 鮮度メタ自動付与)
pdf_bytes = b"..."
new_hash = compute_hash(pdf_bytes)
if has_changed(previous_hash, new_hash):
    freshness = build_freshness(
        source_url="https://www.city.fujisawa.kanagawa.jp/.../page.html",
        source_pdf_url="https://www.city.fujisawa.kanagawa.jp/documents/.../20240401.pdf",
    )
    # → freshness.snapshot_date は filename から自動推定 (2024-04-01)

# (5) Skill File を LLM プロンプトに動的注入
citation_rules = get_skill("citation_format")
freshness_rules = get_skill("freshness_disclaimer")

# (6) 緊急情報 RSS の parse (5 分 poll 自体は consumer 側で実装)
rss_bytes = b"<?xml version='1.0'?><rss version='2.0'><channel>...</channel></rss>"
entries = parse_feed(rss_bytes)
for e in entries:
    if e.guid not in seen_guids:
        ...  # LINE bot に push

# (7) Wayback Machine 経由の過去 PDF バックフィル (Phase 4 の wayback_backfill ETL で利用)
wb_config = WaybackConfig(user_agent="my-app/0.1 (https://example.com)")
async with WaybackClient(wb_config) as wb:
    snaps = await wb.query_cdx(
        "https://www.city.fujisawa.kanagawa.jp/hoiku/documents/r4-4nyuusyonaiteisisuu.pdf",
        from_timestamp="20220101000000",
        mimetype="application/pdf",
    )
    for snap in snaps:
        pdf_bytes = await wb.fetch_archive(snap)
        ...  # Docling で解析 → admission_results に投入
```

---

## 1. 主要モジュール

| モジュール | 役割 | Phase | 状態 |
|---|---|---|---|
| `fujisawa_platform.crawler.polite_fetcher` | UA / interval / If-Modified-Since / 5xx retry を備えた HTTP fetcher | 1 | ✅ 実装済 |
| `fujisawa_platform.crawler.sitemap_loader` | sitemap.xml parser (1,100+ URL、defusedxml 経由) | 1 | ✅ 実装済 |
| `fujisawa_platform.models.common` | `FreshnessMetadata` (鮮度メタデータ) | 1 | ✅ 実装済 |
| `fujisawa_platform.skills` | 共通 Skill File 5 種 + `get_skill()` loader | 1 | ✅ 実装済 |
| `fujisawa_platform.db` | `init_schema.sql` + `get_init_schema_sql()` loader | 1 | ✅ 実装済 |
| `fujisawa_platform.resolver.facility_resolver` | FacilityResolver (rapidfuzz + alias dict、表記ゆれ吸収) | 2 | ✅ 実装済 |
| `fujisawa_platform.knowledge_base.embedding` | Embedding Protocol + Mock + Vertex (`text-embedding-004`、768 dim) | 2 | ✅ 実装済 |
| `fujisawa_platform.knowledge_base.store` | KnowledgeStore Protocol + InMemoryStore (Mock) + PageDocument | 2 | ✅ 実装済 |
| `fujisawa_platform.pdf_pipeline.hash_diff` | SHA-256 差分検知 (ETL の重複処理回避) | 2 | ✅ 実装済 |
| `fujisawa_platform.pdf_pipeline.freshness` | `build_freshness()` + `parse_pdf_date_from_filename()` | 2 | ✅ 実装済 |
| `fujisawa_platform.pdf_pipeline.docling_wrapper` | Docling lazy import + `extract_chunks()` | 2 | ✅ 実装済 |
| `fujisawa_platform.crawler.rss_poller` | 緊急情報 RSS / Atom feed parser (5 分 poll loop は consumer 側) | 3 | ✅ 実装済 |
| `fujisawa_platform.crawler.wayback` | Wayback CDX + Web Archive client (Phase 4 backfill 用) | 3 | ✅ 実装済 |

Phase 4 以降に追加予定:
- `knowledge_base/pgvector_impl.py` (asyncpg + pgvector 本番実装)
- `etl/` (Cloud Run Jobs entrypoints、`wayback_backfill.py` 含む 7 Job)

---

## 2. 環境変数

Phase 1 では env なし。Phase 2 以降で以下を導入予定:

| 変数 | 既定 | 用途 |
|---|---|---|
| `FUJISAWA_PLATFORM_USER_AGENT` | (必須) | crawler の UA。連絡先 URL 含めること |
| `FUJISAWA_PLATFORM_DB_URL` | (必須) | Cloud SQL Postgres 接続 URL |
| `FUJISAWA_PLATFORM_ANALYTICS_ENABLED` | true | analytics-platform への計装 ON/OFF |

---

## 3. DB セットアップ (Phase 1 範囲)

`fujisawa_kb_db` を Cloud SQL (driving-license-bot 既存 instance) に追加する想定。

```bash
# Cloud SQL (gcloud sql)
gcloud sql databases create fujisawa_kb_db --instance=<existing-instance>

# psql で schema 適用
psql $FUJISAWA_PLATFORM_DB_URL -f fujisawa_platform/db/init_schema.sql
```

Python から SQL を取り出すこともできる:

```python
from fujisawa_platform.db import get_init_schema_sql
print(get_init_schema_sql())
```

詳細は proposal 0003 §4.3 / §4.5.3 (IAM ロール分離) 参照。

---

## 4. ETL ジョブ (Phase 2 以降)

proposal 0003 §4.5.4 の通り、Cloud Run Jobs として実装予定:

| Job | 頻度 | 状態 |
|---|---|---|
| `weekly_crawl_etl` | 週次 | ⏳ Phase 4 |
| `monthly_vacancy_etl` | 月次 22 日 | ⏳ Phase 4 |
| `monthly_stats_compute` | 月次 23 日 | ⏳ Phase 4 |
| `half_yearly_facility_etl` | 半年次 | ⏳ Phase 4 |
| `yearly_navi_etl` | 年次 | ⏳ Phase 4 |
| `biyearly_admission_etl` | 年 2 回 | ⏳ Phase 4 |
| `wayback_backfill` | 一度きり | ⏳ Phase 4 |

---

## 5. 関連ドキュメント

- [`../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md`](../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md) — 設計提案
- [`../docs/PROPOSALS/0004-fujisawa-info-bot.md`](../docs/PROPOSALS/0004-fujisawa-info-bot.md) — 利用先 1: 一般情報 LINE bot
- [`../docs/PROPOSALS/0005-fujisawa-hokatsu-agent.md`](../docs/PROPOSALS/0005-fujisawa-hokatsu-agent.md) — 利用先 2: 保活エージェント
- [`../docs/PROPOSALS/notes/fujisawa-platform-investigation-2026-05-09.md`](../docs/PROPOSALS/notes/fujisawa-platform-investigation-2026-05-09.md) — 事前調査結果
- [`fujisawa_platform/skills/`](fujisawa_platform/skills/) — 共通 SKILL.md 5 種
