# fujisawa-platform

藤沢市 HP / PDF を一次ソースとする共通基盤ライブラリ。両エージェント
(`fujisawa-info-bot` / `fujisawa-hokatsu-agent`) が path dep で参照し、
**クロール / PDF 解析 / ベクトル検索 / 出典 Skill / 表記ゆれ吸収 / ETL** を一元提供する。

> **Status**: Phase 4-2h step 3 実装済 (terraform 完成、配備可能状態)

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

# (3) ベクトル検索 (テストは InMemoryStore、本番は PgvectorStore)
from fujisawa_platform.knowledge_base import (
    InMemoryStore,
    PgvectorStore,
    build_pgvector_pool,
)

embedder = MockEmbeddingClient()  # or VertexEmbeddingClient(project_id=...)

# 開発・テスト時
store = InMemoryStore()

# 本番 (uv sync --extra pgvector で導入)
pool = await build_pgvector_pool(
    host="127.0.0.1",  # Cloud SQL Auth Proxy 経由
    user="etl_user", password="...", database="fujisawa_kb_db",
)
store = PgvectorStore(pool=pool, embedding_dim=768)

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

# (8) weekly_crawl_etl (Cloud Run Job として配備、毎週日曜 03:00 JST)
from fujisawa_platform.etl import EtlConfig, run_weekly_crawl
from fujisawa_platform.etl._repos.etl_runs import EtlRunsRepo

config = EtlConfig()  # FUJISAWA_ETL_* env から自動ロード
pool = await build_pgvector_pool(
    host=config.db_host, port=config.db_port,
    user=config.db_user, password=config.db_password, database=config.db_name,
)
try:
    result = await run_weekly_crawl(
        sitemap_url=config.sitemap_url,
        fetcher_config=PoliteFetcherConfig(
            user_agent=config.user_agent,
            min_interval_sec=config.min_interval_sec,
        ),
        embedder=MockEmbeddingClient(),  # or VertexEmbeddingClient(...)
        store=PgvectorStore(pool=pool, embedding_dim=config.embedding_dim),
        runs_repo=EtlRunsRepo(pool=pool),
        run_id=f"weekly_crawl_etl-{datetime.now(UTC):%Y%m%d-%H%M}",
    )
    print(result.status, result.rows_written)  # 'success' 1100
finally:
    await pool.close()
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
| `fujisawa_platform.knowledge_base.pgvector_store` | PgvectorStore (asyncpg + pgvector 本番実装) + `build_pgvector_pool` | 4-1 | ✅ 実装済 |
| `fujisawa_platform.etl._runner` | `run_etl_job()` 共通実行ラッパー (etl_runs 記録 / fail-fast / skip-unchanged) | 4-2a | ✅ 実装済 |
| `fujisawa_platform.etl._repos.etl_runs` | `EtlRunsRepo` | 4-2a | ✅ 実装済 |
| `fujisawa_platform.etl._html` | `extract_main_text` / `extract_title` (BeautifulSoup) | 4-2a | ✅ 実装済 |
| `fujisawa_platform.etl.config` | `EtlConfig` (env: `FUJISAWA_ETL_*`) | 4-2a | ✅ 実装済 |
| `fujisawa_platform.etl.weekly_crawl` | `run_weekly_crawl` / `crawl_and_index` (sitemap → pages) | 4-2a | ✅ 実装済 |
| `fujisawa_platform.etl._repos.facilities` | `FacilitiesRepo` (replace_all) + `FacilityRecord` | 4-2b | ✅ 実装済 |
| `fujisawa_platform.etl._html_table` | `extract_tables_with_links` (BS4 ベース、リンク URL 込み) | 4-2b | ✅ 実装済 |
| `fujisawa_platform.etl.facility_parser` | `parse_authorized_table` / `parse_unauthorized_table` / `slugify_facility_id` | 4-2b | ✅ 実装済 |
| `fujisawa_platform.etl.half_yearly_facility` | `run_half_yearly_facility` / `crawl_and_replace_facilities` (HTML → facilities) | 4-2b | ✅ 実装済 |
| `fujisawa_platform.etl._repos.admission` | `AdmissionRepo.upsert_many` + `AdmissionResultRecord` | 4-2c | ✅ 実装済 |
| `fujisawa_platform.pdf_pipeline.pdf_table` | `extract_tables` / `PdfTable` (Docling lazy) | 4-2c | ✅ 実装済 |
| `fujisawa_platform.etl.admission_parser` | `parse_admission_table` + `parse_min_index_notation` | 4-2c | ✅ 実装済 |
| `fujisawa_platform.etl.facility_resolver_builder` | `build_facility_resolver` (FacilitiesRepo → FacilityResolver) | 4-2c | ✅ 実装済 |
| `fujisawa_platform.etl.biyearly_admission` | `run_biyearly_admission` / `crawl_and_upsert_admission` (PDF → admission_results) | 4-2c | ✅ 実装済 |
| `fujisawa_platform.etl.pdf_archive` | `PdfArchive` Protocol + `GcsArchive` / `LocalArchive` / `NullArchive` + `archive_path` + `build_archive_from_config` | 4-2c-2 | ✅ 実装済 |
| `fujisawa_platform.etl._repos.vacancy` | `VacancyRepo` / `ApplicationRepo` + `VacancySnapshotRecord` / `ApplicationSnapshotRecord` | 4-2d | ✅ 実装済 |
| `fujisawa_platform.etl.vacancy_parser` | `parse_vacancy_table` / `parse_application_table` | 4-2d | ✅ 実装済 |
| `fujisawa_platform.etl.monthly_vacancy` | `run_monthly_vacancy` / `crawl_and_upsert_vacancy` (空き + 申込 PDF → snapshots、PdfArchive 統合) | 4-2d | ✅ 実装済 |
| `fujisawa_platform.etl._repos.pdf_documents` | `PdfDocumentsRepo.replace_for_pdf` + `PdfDocumentRecord` | 4-2e | ✅ 実装済 |
| `fujisawa_platform.etl.yearly_navi` | `run_yearly_navi` / `crawl_and_index_navi` (申込ナビ PDF → pdf_documents、PdfArchive 統合) | 4-2e | ✅ 実装済 |
| `fujisawa_platform.etl._repos.competition_stats` | `CompetitionStatsRepo` + `CompetitionStatsRecord` + `YearlyCompetitionEntry` + `HistoricalMinimumIndex` | 4-2f | ✅ 実装済 |
| `fujisawa_platform.etl.stats_compute` | `compute_competition_stats` + `classify_level` / `classify_trend` / `confidence_from_years` (pure 関数) | 4-2f | ✅ 実装済 |
| `fujisawa_platform.etl.monthly_stats_compute` | `run_monthly_stats_compute` / `compute_stats` (admission 集計 → competition_stats、外部 fetch なし) | 4-2f | ✅ 実装済 |
| `fujisawa_platform.etl.min_index_parser` | `parse_min_index_table` + `MinIndexEntry` (令和 4 年最低指数 PDF) | 4-2g | ✅ 実装済 |
| `fujisawa_platform.etl.wayback_backfill` | `run_wayback_backfill` / `backfill_admissions` / `BackfillItem` (Wayback 経由で令和 4-6 年バックフィル、一度きり) | 4-2g | ✅ 実装済 |
| `fujisawa_platform.etl.cli` | `python -m fujisawa_platform.etl.cli <job_name>` Cloud Run Job dispatcher | 4-2h-1 | ✅ 実装済 |
| `Dockerfile` (project root) | multi-stage build (uv + 4 extras)、1 image で 7 entrypoint | 4-2h-1 | ✅ 実装済 |
| `docs/SETUP.md` | GCP 構築 runbook (terraform 外の手動ステップ) | 4-2h-1 | ✅ 実装済 |
| `terraform/` (step 2) | Cloud SQL DB / Secret Manager / IAM / GCS bucket / Artifact Registry | 4-2h-2 | ✅ 実装済 |
| `terraform/` (step 3) | Cloud Run Jobs × 7 + Cloud Scheduler × 6 (定期 6 + wayback_backfill 手動 trigger) | 4-2h-3 | ✅ 実装済 |

Phase 4-2d 以降に追加予定:
- `etl/monthly_vacancy.py` + `VacancyRepo` (PDF → vacancy / application snapshots)
- `etl/yearly_navi.py` + `PdfDocumentsRepo` (申込ナビ PDF → pdf_documents)
- `etl/monthly_stats_compute.py` + `CompetitionStatsRepo` (DB 内集計)
- `etl/wayback_backfill.py` (令和 4-6 年データ、一度きり)
- terraform: Cloud Run Jobs / Cloud Scheduler / Secret Manager (Phase 4-2h)

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
