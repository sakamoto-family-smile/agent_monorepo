# fujisawa-platform 設計書

| | |
|---|---|
| **Version** | 0.6 |
| **最終更新** | 2026-05-10 |
| **Status** | Active (Phase 4-2b 実装済 / Phase 4-2c 着手予定) |
| **Owner** | @kurama554101 |
| **Type** | 共通基盤ライブラリ (path dep として info-bot / 保活 から参照) |
| **README** | [`../README.md`](../README.md) |

## 変更履歴

| 日付 | Version | 変更内容 |
|---|---|---|
| 2026-05-09 | 0.1 | 初版 (Phase 1: パッケージ雛形 + crawler + skills + DB schema) |
| 2026-05-09 | 0.2 | Phase 2 実装 (resolver / knowledge_base + Mock backends / pdf_pipeline) |
| 2026-05-10 | 0.3 | Phase 3 実装 (crawler/rss_poller + crawler/wayback) |
| 2026-05-10 | 0.4 | Phase 4-1 実装 (knowledge_base/pgvector_store: asyncpg + pgvector 本番) |
| 2026-05-10 | 0.5 | Phase 4-2a 実装 (etl 共通フレーム + weekly_crawl_etl) |
| 2026-05-10 | 0.6 | Phase 4-2b 実装 (half_yearly_facility_etl + FacilitiesRepo + facility_parser) |

---

## 0. Executive Summary

藤沢市 HP / PDF を一次ソースとする 2 エージェント (`fujisawa-info-bot` / `fujisawa-hokatsu-agent`)
が共通で依存する基盤ライブラリ。クロール / PDF 解析 / 鮮度メタデータ / ベクトル検索 /
出典 Skill / 表記ゆれ吸収 / ETL を一元提供し、二重 fetch を排除する。

設計の根拠・経緯は **proposal 0003** に集約しており、本ドキュメントは
**「実装の現況とリンク先」のインデックス** として機能する。

---

## 1. 設計原典

| 文書 | 内容 |
|---|---|
| [`PROPOSAL-0003`](../../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md) | 機能要件 / NFR / アーキ / DB schema / ETL タイミング / ADR |
| [`PROPOSAL-0004`](../../docs/PROPOSALS/0004-fujisawa-info-bot.md) | 利用先 1: 藤沢市情報 LINE Bot |
| [`PROPOSAL-0005`](../../docs/PROPOSALS/0005-fujisawa-hokatsu-agent.md) | 利用先 2: 保活エージェント |
| [`notes/fujisawa-platform-investigation-2026-05-09.md`](../../docs/PROPOSALS/notes/fujisawa-platform-investigation-2026-05-09.md) | 事前調査結果 (M1〜M11 修正点 + Wayback バックフィル可能性) |

本 DESIGN.md は実装が proposal の範囲を超えた場合や、Phase 進捗で確定した詳細を追記する用途。

---

## 2. 実装フェーズ (proposal 0003 §3.1 から転記)

| Phase | 内容 | 状態 |
|---|---|---|
| **Phase 1** | パッケージ雛形 + polite_fetcher + sitemap_loader + skills + DB schema | ✅ 完了 (PR #116) |
| **Phase 2** | resolver (FacilityResolver) + knowledge_base (Embedding Protocol + Mock + Vertex / KnowledgeStore Protocol + InMemoryStore) + pdf_pipeline (hash_diff / freshness / docling lazy) | ✅ 完了 (PR #117) |
| **Phase 3** | crawler/rss_poller + crawler/wayback | ✅ 完了 (PR #118) |
| **Phase 4-1** | knowledge_base/pgvector_store (asyncpg + pgvector 本番) + build_pgvector_pool | ✅ 完了 (PR #119) |
| **Phase 4-2a** | etl 共通フレーム (`_runner` / `EtlRunsRepo` / `_html` / `config`) + `weekly_crawl_etl` | ✅ 完了 (PR #120) |
| **Phase 4-2b** | `half_yearly_facility_etl` + `FacilitiesRepo` + `facility_parser` + `_html_table` | 🔶 実装済 (本 PR) |
| Phase 4-2c〜g | `biyearly_admission` / `monthly_vacancy` / `yearly_navi` / `monthly_stats_compute` / `wayback_backfill` | ⏳ 未着手 |
| Phase 4-2h | terraform: Cloud Run Jobs / Cloud Scheduler / Secret Manager | ⏳ 未着手 |
| Phase 5 | observability (analytics-platform 計装) + monitoring | ⏳ 未着手 |

---

## 3. Phase 4-2b で確定した詳細

### 3.0 設計判断

- **`facilities` は全削除 → 全 INSERT を 1 トランザクション**: proposal 0003 §4.5.5 の方針。半年に 1 回しか走らず、件数が ~160 と小さいため UPSERT 並列より単純で安全。consumer 側は SELECT 失敗時に tenacity retry で吸収する想定。
- **facility_id は `<type-slug>-<sha256[:12]>`**: 名前ベースの決定的 ID。半年ごとに replace_all しても同じ施設には同じ ID が返るので、`vacancy_snapshots.facility_id REFERENCES facilities` の FK が壊れない。例: `kouritsu-3a4b5c6d7e8f` (公立保育所 / 藤沢保育園)。
- **HTML テーブル抽出は BeautifulSoup 単独で完結**: 調査ノート §A4-3 では `pandas.read_html` + BS4 の 2 段だったが、リンク URL を別途 BS4 で取り直すなら最初から BS4 で `<th>` / `<td>` を見れば十分。pandas 依存を避け、`_html_table.py` 1 ファイルで完結させた。
- **認可テーブル 5 種は HTML 内の出現順で type を割当**: `_AUTHORIZED_TABLE_TYPES = ["公立保育所", "法人等保育所", "認定こども園", "小規模保育事業", "家庭的保育事業"]`。HTML 構造が変わってテーブルが減った場合は `zip(strict=False)` で parsable な範囲だけ処理する fallback。
- **認可外の facility_type は施設名末尾の括弧から抽出**: 「A 保育園 (藤沢型 A 型)」→ name="A 保育園", facility_type="藤沢型 A 型"。括弧無しは "認可外保育施設" にフォールバック。
- **アクセス情報の駅 + 徒歩分数は所在地カラムから regex 抽出**: 「藤沢駅北口徒歩 7 分」のような表記を `_WALK_MINUTES` で parse。マッチしないなら `(None, None)` で通常の住所扱い。

### 3.1 `FacilitiesRepo` (`etl/_repos/facilities.py`)

| メソッド | 仕様 |
|---|---|
| `replace_all(records)` | `async with conn.transaction(): DELETE → INSERT × N`。空 list でも DELETE は実行 (古いマスタを残さない) |
| `count()` | `SELECT COUNT(*) FROM facilities` (smoke / 監視用) |
| 引数 jsonb | `aliases` は `json.dumps(..., ensure_ascii=False)` で `$10::jsonb` バインド (asyncpg は文字列を json型に渡せる) |

実装: [`fujisawa_platform/etl/_repos/facilities.py`](../fujisawa_platform/etl/_repos/facilities.py)
テスト: 7 ケース PASS

### 3.2 HTML テーブル抽出 (`etl/_html_table.py`)

| 観点 | 仕様 |
|---|---|
| 関数 | `extract_tables_with_links(html) -> list[HtmlTable]` |
| `HtmlTable` | `headers: list[str]` / `rows: list[list[str]]` / `row_links: list[dict[int, str]]` |
| ヘッダ検出 | `<thead>` 優先 → 1 行目が全て `<th>` ならそれを headers → なければ空 list |
| リンク抽出 | 各セル内の最初の `<a href>` を `row_links[行 idx][列 idx]` に格納 |
| セルテキスト | `get_text(strip=True)` で前後空白除去 |

実装: [`fujisawa_platform/etl/_html_table.py`](../fujisawa_platform/etl/_html_table.py)
テスト: 8 ケース PASS

### 3.3 facility_parser (`etl/facility_parser.py`)

| 関数 | 用途 |
|---|---|
| `slugify_facility_id(facility_type, name)` | `<type-slug>-<sha256[:12]>` の決定的 ID 生成 |
| `parse_walk_minutes(text)` | 「藤沢駅北口徒歩 7 分」→ ("藤沢駅", 7)。マッチなしは (None, None) |
| `parse_authorized_table(*, table, facility_type, source_url, as_of)` | 認可施設テーブル (3 列以上) → `list[FacilityRecord]`。4 列目以降のリンクを `official_url` に採用 |
| `parse_unauthorized_table(*, table, source_url, as_of)` | 認可外 (4 列以上) → `list[FacilityRecord]`。括弧内類型 + 駅徒歩分数 + 定員を parse |

実装: [`fujisawa_platform/etl/facility_parser.py`](../fujisawa_platform/etl/facility_parser.py)
テスト: 17 ケース PASS

### 3.4 `half_yearly_facility_etl` (`etl/half_yearly_facility.py`)

| 観点 | 仕様 |
|---|---|
| 起動 | `run_half_yearly_facility(*, authorized_url, unauthorized_url, fetcher_config, facilities_repo, runs_repo, run_id, ...)` |
| 処理 | 認可 + 認可外 HTML を polite fetch → テーブル抽出 → parse → `FacilitiesRepo.replace_all` |
| dry-run | parse は行うが `repo.replace_all` を呼ばない (rows_written は parse 件数) |
| source_hash | 認可 + 認可外 の SHA-256 を合成して 1 つの hash に (どちらかでも変われば run する) |
| 個別 fetch 失敗 | `httpx.HTTPStatusError` を上位に伝搬 → `run_etl_job` ラッパー側で `failed` 扱い |
| 認可外テーブル空 | 認可分のみ upsert される (facilities が完全に消えるリスクを避ける) |

実装: [`fujisawa_platform/etl/half_yearly_facility.py`](../fujisawa_platform/etl/half_yearly_facility.py)
テスト: 6 ケース PASS

---

## 4. Phase 4-2a で確定した詳細

### 4.0 設計判断

- **ETL 共通フレームを最初に整備**: `etl/_runner.py` (実行ラッパー) / `etl/_repos/etl_runs.py` (`etl_runs` テーブル) / `etl/_html.py` (本文抽出) / `etl/config.py` (env) の 4 つを 4-2a で同梱。これ以降の Job (4-2b〜g) はすべて `run_etl_job()` で包む。
- **`run_etl_job()` の 3 つの責務** (proposal 0003 §4.5.6):
  - **記録**: `etl_runs` に `started_at` で INSERT (`status='running'`) → 終了時に UPDATE (`status='success'|'failed'|'skipped_unchanged'`)
  - **fail-fast**: 直近 5 件すべて failed なら fn を呼ばずに `status='failed'` で記録 (再開は手動)
  - **source_hash skip**: `probe()` で計算した hash が前回 success と一致なら fn を呼ばずに `status='skipped_unchanged'`
- **個別 URL の例外は continue**: `weekly_crawl_etl` は 1,100+ URL を順に叩くため、1 URL の 4xx/5xx で全体を fail させない。`failed_urls` カウンタで追跡し、Job 全体は `success` で完了する (個別失敗は別途監視で検知)。
- **dry-run mode**: 各 Job は `dry_run=True` で **DB 書き込み無し / parse は行う** モードを持つ。Cloud Run Job デプロイ前の手動 smoke 用 (proposal 0003 §4.6 Manual / E2E)。
- **`_StoreLike` Protocol で DI**: `crawl_and_index` は `upsert_page` だけを持つ Protocol を要求するので、`PgvectorStore` (本番) / `InMemoryStore` (smoke) / `_RecordingStore` (テスト) が等しく差し込める。

### 4.1 `run_etl_job` ラッパー (`etl/_runner.py`)

| 観点 | 仕様 |
|---|---|
| 入力 | `job_name` / `run_id` / `repo: EtlRunsRepo` / `fn: () -> EtlRunResult` / 任意 `probe` / 任意 `now` |
| fail-fast | `repo.recent_runs(limit=5)` の全件 `failed` なら fn 呼ばず即時 failed |
| skip-unchanged | `probe()` の戻り値が `recent_runs` 中の最新 success の `source_hash` と一致なら `skipped_unchanged` |
| 例外捕捉 | fn 内例外は `<ClassName>: <message>` 形式で `error_message` に詰めて failed 扱い |
| 戻り値 | `EtlRunResult` (`rows_written` / `source_hash` / `source_url` / `status` / `error_message`) |

実装: [`fujisawa_platform/etl/_runner.py`](../fujisawa_platform/etl/_runner.py)
テスト: 8 ケース PASS

### 4.2 `EtlRunsRepo` (`etl/_repos/etl_runs.py`)

| メソッド | 仕様 |
|---|---|
| `start_run(*, job_name, run_id, started_at, source_url=None)` | `INSERT INTO etl_runs (..., status='running')` |
| `finish_run(*, job_name, run_id, finished_at, status, source_hash=None, rows_written=None, error_message=None)` | `UPDATE etl_runs SET status, finished_at, source_hash, rows_written, error_message WHERE job_name AND run_id` |
| `recent_runs(job_name, *, limit=5)` | `ORDER BY started_at DESC LIMIT $2`、5 連敗 fail-fast 判定で利用 |

実装: [`fujisawa_platform/etl/_repos/etl_runs.py`](../fujisawa_platform/etl/_repos/etl_runs.py)
テスト: 6 ケース PASS

### 4.3 HTML 本文抽出 (`etl/_html.py`)

| 観点 | 仕様 |
|---|---|
| `extract_main_text(html)` | 優先順位: `<main>` → `<article>` → `<body>`。`<script>` / `<style>` / `<nav>` / `<footer>` / `<header>` / `<aside>` を decompose で除去 |
| `extract_title(html)` | `<title>` → `<h1>` の順で取得。Unicode (令和6年 等) は intact |
| 連続空白 | 1 つに正規化 (改行は保つ) |

実装: [`fujisawa_platform/etl/_html.py`](../fujisawa_platform/etl/_html.py)
テスト: 12 ケース PASS

### 4.4 `EtlConfig` (`etl/config.py`)

| グループ | env 変数 |
|---|---|
| DB | `FUJISAWA_ETL_DB_HOST` / `_PORT` (5432) / `_USER` / `_PASSWORD` / `_NAME` (`fujisawa_kb_db`) / `_POOL_MIN` / `_POOL_MAX` |
| HTTP | `FUJISAWA_ETL_USER_AGENT` (連絡先 URL 必須) / `_MIN_INTERVAL_SEC` (3.0) |
| Embedding | `FUJISAWA_ETL_VERTEX_PROJECT_ID` (None なら Mock) / `_VERTEX_LOCATION` / `_EMBEDDING_MODEL` / `_EMBEDDING_DIM` |
| Job 個別 | `FUJISAWA_ETL_<JOB>_ENABLED` (例: `WEEKLY_CRAWL_ENABLED`) — Phase 0 で段階導入 |

実装: [`fujisawa_platform/etl/config.py`](../fujisawa_platform/etl/config.py)
テスト: 4 ケース PASS

### 4.5 `weekly_crawl_etl` (`etl/weekly_crawl.py`)

| 観点 | 仕様 |
|---|---|
| 起動 | `run_weekly_crawl(*, sitemap_url, fetcher_config, embedder, store, runs_repo, run_id, ...)` |
| 処理 | sitemap.xml fetch → parse → 各 URL polite fetch → main 抽出 → embed → upsert_page |
| 304 handling | `NotModified` を受けたら `skipped_not_modified` カウント、upsert なし |
| 個別 URL 失敗 | 例外 (httpx.HTTPError) は捕捉して continue、`failed_urls` カウント |
| 空本文 | `extract_main_text` が空文字を返したら `skipped_empty` カウント、upsert なし |
| dry-run | parse は行うが `store.upsert_page` を呼ばず、`rows_written` は parse 件数 |
| source_hash | sitemap.xml 全体の SHA-256 を `EtlRunResult.source_hash` に詰める |

実装: [`fujisawa_platform/etl/weekly_crawl.py`](../fujisawa_platform/etl/weekly_crawl.py)
テスト: 7 ケース PASS

### 4.6 Phase 4-2 後続 Job への引き継ぎ

各 Job は本 PR で整備した `run_etl_job` パターンに沿って実装する:

```python
async def run_<job_name>(*, ..., runs_repo, run_id, ...):
    async def _job() -> EtlRunResult:
        # 1. fetch (PoliteFetcher / WaybackClient)
        # 2. parse (Docling / BeautifulSoup / pandas)
        # 3. resolve facility_id (FacilityResolver)
        # 4. upsert (PgvectorStore / FacilitiesRepo / VacancyRepo / ...)
        return EtlRunResult(rows_written=..., source_hash=...)

    return await run_etl_job(
        job_name="<job_name>",
        run_id=run_id,
        repo=runs_repo,
        fn=_job,
    )
```

---

## 5. Phase 4-1 で確定した詳細

### 5.0 設計判断

- **PgvectorStore は `asyncpg.Pool` を外部から受け取る**: クラス内で pool を作らず、consumer 側 (ETL Job / agent main) のライフサイクルでクローズする。短命接続を避けて Cloud SQL の同時接続上限を保護。driving-license-bot の `PgvectorQuestionBank` と同パターン。
- **`pgvector.asyncpg.register_vector` は 1 クエリごとに呼ぶ**: Pool から acquire される接続は再利用されるが、再利用時の register は no-op になる前提で愚直に呼ぶ (driving-license-bot と同方針)。
- **cosine 距離は `<=>` 演算子、類似度は `1 - (<=>)`**: pgvector 標準。HNSW より ivfflat (`lists=100`) を schema で採用済 (proposal §4.3)。
- **asyncpg / pgvector は lazy import**: `[pgvector]` extra なしでも fujisawa-platform を import できるようにする (consumer が in-memory のみ使うケースを許容)。
- **pgvector 単体テストは asyncpg を mock**: 実 Cloud SQL は CI に持たない。proposal §4.6 の通り、接続 smoke は Phase 4-2 ETL デプロイ時に手動。

### 5.1 PgvectorStore の挙動

| 観点 | 仕様 |
|---|---|
| 入力 | `pool: asyncpg.Pool` (外部構築) + `embedding_dim` (default 768) |
| `upsert_page` | `INSERT ... ON CONFLICT (page_id) DO UPDATE`。dimension 不一致は DB を叩く前に ValueError |
| `get_page` | `SELECT ... WHERE page_id = $1`。numpy.ndarray を `.tolist()` で list 化 |
| `delete_page` | `DELETE FROM pages WHERE page_id = $1`。`DELETE N` の N で True/False 判定 (parse 失敗は False) |
| `search_pages` | `1 - (embedding <=> $1) AS score` + `ORDER BY embedding <=> $1`。category フィルタは `WHERE ($2::text IS NULL OR category = $2)` |
| dimension 検証 | upsert / search 時に query/embedding の次元が `embedding_dim` と一致するか確認 |

実装: [`fujisawa_platform/knowledge_base/pgvector_store.py`](../fujisawa_platform/knowledge_base/pgvector_store.py)
テスト: 16 ケース PASS (asyncpg mock)

### 5.2 build_pgvector_pool helper

| 観点 | 仕様 |
|---|---|
| 引数 | `host` / `port=5432` / `user` / `password` / `database` / `min_size=1` / `max_size=5` |
| 戻り値 | `asyncpg.Pool` |
| Cloud SQL Auth Proxy | `host="127.0.0.1"` を渡すだけで対応可能 |
| ライフサイクル | 呼出側が `await pool.close()` する (本ライブラリは管理しない) |

実装: 同上 (`pgvector_store.py` 末尾)

### 5.3 Phase 4-2 への引き継ぎ

`weekly_crawl_etl` (Phase 4-2 で実装予定) の典型的な処理フロー:

```
[1] sitemap.xml 取得 (PoliteFetcher)
    └─ FetchResult.text を bytes に encode して parse_sitemap に渡す
[2] parse_sitemap → list[SitemapEntry] (~1,100 URL)
[3] 各 URL を polite fetch (1 URL/3s、 1,100 URL ≈ 1 時間)
[4] HTML 本文抽出 + Vertex Embedding
[5] PgvectorStore.upsert_page で Cloud SQL に upsert
```

完全な擬似コード:

```python
async def weekly_crawl():
    fetcher_config = PoliteFetcherConfig(
        user_agent="fujisawa-platform-etl/0.1 (https://example.com/contact)",
        min_interval_sec=3.0,
    )
    pool = await build_pgvector_pool(
        host=os.environ["DB_HOST"], user=..., password=..., database="fujisawa_kb_db",
    )
    try:
        store = PgvectorStore(pool=pool, embedding_dim=768)
        embedder = VertexEmbeddingClient(project_id=..., model="text-embedding-004")

        async with PoliteFetcher(fetcher_config) as fetcher:
            # [1][2] sitemap.xml を fetch → parse
            sitemap_url = "https://www.city.fujisawa.kanagawa.jp/sitemap.xml"
            sitemap_result = await fetcher.fetch(sitemap_url)
            sitemap_bytes = sitemap_result.text.encode("utf-8")
            entries = parse_sitemap(sitemap_bytes)  # list[SitemapEntry]

            # [3][4][5] 各 URL を polite fetch → embed → upsert
            for entry in entries:
                page_result = await fetcher.fetch(str(entry.url))
                if isinstance(page_result, NotModified):
                    continue  # 304 → upsert skip
                text = clean_html(page_result.text)
                await store.upsert_page(PageDocument(
                    page_id=hash_url(str(entry.url)),
                    url=str(entry.url),
                    content=text,
                    embedding=embedder.embed(text),
                    fetched_at=datetime.now(UTC),
                    last_modified=page_result.last_modified,
                ))
    finally:
        await pool.close()
```

`sitemap_bytes` は **(1) PoliteFetcher で `https://www.city.fujisawa.kanagawa.jp/sitemap.xml` を取得 → (2) `FetchResult.text` を utf-8 エンコード** で得る。藤沢市 HP の sitemap.xml は約 1,100 URL を含む (proposal 0003 §A3-2 / Phase 1 調査結果)。

---

## 6. Phase 3 で確定した詳細

### 6.0 設計判断

- **緊急情報 RSS の 5 分 poll loop は LINE bot 側に置く**: 共通基盤側は `parse_feed(bytes) -> list[RssEntry]` の純粋な parse helper のみ提供する (proposal 0003 §4.5.4 の方針: 「5 分間隔の job が他 consumer にも見えると混乱する」)。LINE bot 側 `fujisawa-info-bot/batch/poll_rss.py` が `seen_guids` セットを Firestore で管理する。
- **`parse_feed` は RSS 2.0 / Atom 両対応**: 藤沢市 HP がどちらを返すか実機未確認のため、両 schema を 1 関数で吸収。`<rss>` / `<feed>` のルート要素で分岐。
- **Wayback クライアントは `PoliteFetcher` を流用しない**: web.archive.org は別ホストで polite ルール (5 秒間隔 / 503 retry) も別。共通化するメリットより独立 client の方が単純。
- **CDX クエリは statuscode != 200 を捨てる**: Wayback には 404 / 301 のスナップショットも履歴として残るが、PDF 取得は不可能のため `_rows_to_snapshots` で除外。
- **Wayback バックフィルは Phase 4 で 1 度きり実行**: 本 PR ではクライアント実装のみ。実データ投入は Phase 4 の `etl/wayback_backfill.py` で `admission_results` (令和 4-6 年) + `competition_stats.historical_minimum_index_2022` に流し込む。

### 6.1 緊急情報 RSS parser (`crawler/rss_poller.py`)

| 観点 | 仕様 |
|---|---|
| 関数 | `parse_feed(content: bytes) -> list[RssEntry]` |
| 対応 schema | RSS 2.0 (`<rss><channel><item>`) / Atom (`<feed><entry>`) |
| 必須要素 | `<title>` / `<link>` (`href`)。欠落で `RssParseError` |
| 一意キー (guid) | RSS: `<guid>` → 不在なら `<link>` / Atom: `<id>` → 不在なら `href` |
| 公開日時 | RSS: `<pubDate>` (RFC 822) / Atom: `<updated>` → 失敗時 `published=None` (entry は捨てない) |
| Atom link 解決 | `rel="alternate"` を最優先、無ければ `rel` 無し、それも無ければ最初の link |
| XML safety | `defusedxml` で XXE / billion laughs 対策 (sitemap_loader と同じ) |
| 非対応 | HTTP fetch / 5 分 poll loop / `seen_guids` 重複排除 (consumer 側責務) |

実装: [`fujisawa_platform/crawler/rss_poller.py`](../fujisawa_platform/crawler/rss_poller.py)
テスト: 16 ケース PASS

### 6.2 Wayback クライアント (`crawler/wayback.py`)

| 観点 | 仕様 |
|---|---|
| エンドポイント | CDX: `https://web.archive.org/cdx/search/cdx?output=json` / Archive: `https://web.archive.org/web/{ts}/{orig}` |
| 礼儀 | `min_interval_sec=5.0` (web.archive.org への配慮、proposal §A2) |
| 503 handling | `max_retries=5` (default) / 指数バックオフ / 連続 fail で `WaybackError` (再開は手動) |
| 4xx handling | fail-fast。retry せず即時 `WaybackError` |
| `query_cdx()` | `from_timestamp` / `to_timestamp` / `mimetype` で絞り込み可。statuscode != 200 のスナップショットは除外 |
| `fetch_archive()` | `WaybackSnapshot.archive_url` 経由で生バイト取得 (404 = snapshot 消失で WaybackError) |
| `build_archive_url()` | timestamp + 元 URL から archive URL を組み立てる decodable なヘルパー |
| 利用想定 | Phase 4 の `etl/wayback_backfill.py` で 1 度きり (令和 4-6 年 PDF) |

実装: [`fujisawa_platform/crawler/wayback.py`](../fujisawa_platform/crawler/wayback.py)
テスト: 19 ケース PASS

### 6.3 Phase 4-2 への引き継ぎ事項

`etl/wayback_backfill.py` (Phase 4-2 で実装予定) の擬似コード:

```python
async def backfill():
    config = WaybackConfig(user_agent="fujisawa-platform-etl/0.1 (https://...)")
    async with WaybackClient(config) as client:
        for index_url in [
            "https://www.city.fujisawa.kanagawa.jp/hoiku/20160218.html",
        ]:
            snapshots = await client.query_cdx(
                index_url,
                from_timestamp="20220101000000",
                to_timestamp="20251231235959",
            )
            for snap in snapshots:
                html = await client.fetch_archive(snap)
                # → BeautifulSoup で `documents/*.pdf` リンク抽出
                # → 個別 PDF を query_cdx + fetch_archive
                # → Docling 抽出 → admission_results / competition_stats に upsert
```

---

## 7. Phase 2 で確定した詳細

### 7.0 設計判断

- **PgvectorStore (本番 asyncpg 実装) は Phase 4 に延期**: Cloud SQL への接続ライフサイクルが ETL Cloud Run Jobs と一体のため、Phase 4 で同時に実装。Phase 2 範囲では Protocol + InMemoryStore (Mock) を提供。
- **Embedding は Protocol + Mock + Vertex の 3 段構成**: driving-license-bot の `app/agent/embedding.py` パターンを踏襲。Vertex は lazy import (`uv sync --extra vertex` で導入)。
- **Docling は完全 lazy import**: `[pdf]` extra として ML deps を分離。Phase 4 ETL でのみ必要。
- **rapidfuzz scorer は `fuzz.ratio` (Levenshtein)**: 日本語は token boundaries が無いため、token-set ratio より文字レベル ratio が中黒 (なかぐろ「・」、例: 「キディ鵠沼・藤沢」⇔「キディ鵠沼藤沢」) / typo に強い。

### 7.1 FacilityResolver の挙動

| 観点 | 仕様 |
|---|---|
| 入力 | `query` (検索文字列) + `entries` (ResolverEntry のリスト) |
| 解決経路 | 1. canonical / alias 完全一致 (score=1.0) 2. fuzz.ratio で fuzzy match |
| threshold | default 0.85 (中黒「・」の有無 / 軽微 typo を吸収) |
| `resolve()` | 最高スコアを 1 つ返す。threshold 未満は `NoMatchError` |
| `resolve_all(top_k)` | score 降順で top-k。同 facility_id は最高スコアのみ |
| 重複排除 | canonical と alias 両方にヒットしても 1 件にまとめる |

実装: [`fujisawa_platform/resolver/facility_resolver.py`](../fujisawa_platform/resolver/facility_resolver.py)
テスト: 13 ケース PASS

### 7.2 EmbeddingClient の Protocol

| 観点 | 仕様 |
|---|---|
| Protocol | `dimension` プロパティ + `embed(text) -> list[float]` + `embed_batch(texts)` |
| MockEmbeddingClient | SHA-256 ハッシュベースで決定的、L2 正規化済 (cosine = 内積) |
| VertexEmbeddingClient | `text-embedding-004` (768 dim)、認証は Workload Identity、import は lazy |
| 次元 | default 768 (Vertex `text-embedding-004` に合わせる) |

実装: [`fujisawa_platform/knowledge_base/embedding.py`](../fujisawa_platform/knowledge_base/embedding.py)
テスト: 10 ケース PASS

### 7.3 KnowledgeStore (pages テーブル抽象)

| 観点 | 仕様 |
|---|---|
| Protocol | `upsert_page` / `get_page` / `delete_page` / `search_pages` (全部 async) |
| InMemoryStore | dict ベース、cosine = 内積で full scan top-k |
| 検索フィルタ | `category` で絞り込み (将来 region / age_class 等を追加) |
| dimension 検証 | upsert / search 時に embedding 次元が store の `embedding_dim` と一致するか確認 |
| 本番 PgvectorStore | Phase 4 で追加 (本 PR は雛形のみ) |

実装: [`fujisawa_platform/knowledge_base/store.py`](../fujisawa_platform/knowledge_base/store.py)
テスト: 11 ケース PASS

### 7.4 pdf_pipeline の 3 helpers

| Helper | 仕様 |
|---|---|
| `compute_hash(bytes) -> str` | SHA-256 hex digest (64 char、小文字) |
| `has_changed(prev, curr)` | None なら常に True (初回)、それ以外は case-insensitive 比較 |
| `build_freshness(...)` | FreshnessMetadata を構築。`snapshot_date` 省略時は PDF URL から自動推定 |
| `parse_pdf_date_from_filename(url)` | YYYYMMDD パターンを正規表現で抽出。1 桁日付など不規則ケースは None |
| `extract_chunks(pdf_bytes)` | Docling lazy import、章見出しで分割した `PdfChunk` のリストを返す |

実装: [`fujisawa_platform/pdf_pipeline/`](../fujisawa_platform/pdf_pipeline/)
テスト: 17 ケース PASS (hash 8 + freshness 9、docling は環境依存で skip)

---

## 8. Phase 1 で確定した詳細

### 8.1 PoliteFetcher の挙動

| 観点 | 仕様 |
|---|---|
| 同時接続 | 1 (内部 `asyncio.Lock`) |
| min_interval_sec | default 3.0 (本番は env で設定) |
| 5xx | tenacity の指数バックオフで `max_retries=3` 回までリトライ |
| 4xx | fail fast (リトライしない) |
| 304 Not Modified | `NotModified` 値で返す (例外ではない) |
| User-Agent | `PoliteFetcherConfig.user_agent` 必須、空文字は構築段階で弾く |
| Last-Modified | レスポンスヘッダから RFC 1123 形式を parse、失敗時 None |

実装: [`fujisawa_platform/crawler/polite_fetcher.py`](../fujisawa_platform/crawler/polite_fetcher.py)
テスト: 11 ケース PASS

### 8.2 sitemap.xml の parse 仕様

| 観点 | 仕様 |
|---|---|
| ルート要素 | `<urlset>` (sitemap.org namespace 必須) |
| 抽出フィールド | `<loc>` (必須) / `<lastmod>` (任意) |
| `<lastmod>` フォーマット | ISO datetime (`2026-04-15T03:00:00+09:00`) または date (`2026-05-01`) |
| 空 `<urlset>` | 空 list を返す (error にしない) |
| 順序 | 出現順を保つ |
| 不正 XML | `SitemapParseError` (ValueError 派生) |

実装: [`fujisawa_platform/crawler/sitemap_loader.py`](../fujisawa_platform/crawler/sitemap_loader.py)
テスト: 12 ケース PASS

### 8.3 Skill File 5 種

| Skill | 用途 | LINE Bot / 保活 |
|---|---|---|
| `citation_format` | 出典 URL + 最終確認日 + 免責のフォーマット | 両方 |
| `freshness_disclaimer` | 鮮度経過日数 + 元 PDF 直リンク + 電話番号併記 | 両方 (特に保活 VacancyAgent) |
| `yasashii_nihongo` | tsutaeru.cloud 誘導 (自前変換しない) | 主に info-bot |
| `escalate_to_municipal` | 窓口連絡先 + 判定基準 | 両方 |
| `line_output_format` | LINE 文字数制約 / 改行 / 絵文字ガイド / Flex 使用ケース | 両方 |

実装: [`fujisawa_platform/skills/`](../fujisawa_platform/skills/)
loader: `fujisawa_platform.skills.get_skill(name)`
テスト: 11 ケース PASS (各 skill が 100 char 以上 + ヘッダ規約準拠)

### 8.4 pgvector schema (8 テーブル)

`fujisawa_kb_db` に作成。proposal 0003 §4.3 + 0005 で言及した全テーブルを網羅:

- `pages` / `pdf_documents` (RAG 用)
- `facilities` (160 件マスタ)
- `vacancy_snapshots` / `application_snapshots` (月次)
- `admission_results` (令和 4 年最低内定指数カラムを含む)
- `competition_stats` (`historical_minimum_index_2022` を JSONB)
- `etl_runs` (差分検知 + 失敗追跡)

実装: [`fujisawa_platform/db/init_schema.sql`](../fujisawa_platform/db/init_schema.sql)
loader: `fujisawa_platform.db.get_init_schema_sql()`
テスト: 5 ケース PASS

---

## 9. NFR (proposal 0003 §3 から要約)

| 観点 | 目標 / 制約 |
|---|---|
| 性能 | crawler 1 URL/3s、sitemap 全クロール 1 時間 / pgvector top-10 < 200ms p95 |
| コスト | Cloud SQL instance 共有で月 ¥0 増、Vertex Embedding 月 ¥10 以下 |
| プライバシー | public 情報のみ扱う、PII は consumer 側 |
| 可用性 | sitemap 取得失敗時は旧データ温存 |
| 保守性 | カバレッジ目標 80%、Phase 1 の crawler / skills / db は 90%+ 達成済 |

詳細は proposal 0003 §3 / §5.4 参照。

---

## 10. 関連ドキュメント

- [`../README.md`](../README.md) — Quickstart / 利用方法
- proposal 0003-0005 (上記 §1)
- 事前調査ノート (上記 §1)
- [`fujisawa_platform/skills/`](../fujisawa_platform/skills/) — 共通 SKILL.md 5 種
- [`fujisawa_platform/db/init_schema.sql`](../fujisawa_platform/db/init_schema.sql) — pgvector schema

---

## 11. 用語集

| 用語 | 意味 |
|---|---|
| polite fetcher | UA 明示 + interval + IfMS を強制する礼儀正しい HTTP 取得層 |
| Wayback バックフィル | Internet Archive 経由で過去 PDF を取得する手法 |
| 鮮度メタデータ | `as_of` / `source_url` / `snapshot_date` を含む共通型 (`FreshnessMetadata`) |
| consumer (本基盤の) | path dep で本ライブラリを使う 2 エージェント (info-bot / 保活) |
| etl_role / consumer_role | DB の IAM ロール分離 (proposal 0003 §4.5.3) |
| `historical_minimum_index_2022` | 令和 4 年の最低内定指数。proposal 0005 のハイブリッドモデル用 (M8) |
