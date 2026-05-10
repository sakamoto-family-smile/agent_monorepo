# fujisawa-platform 設計書

| | |
|---|---|
| **Version** | 0.4 |
| **最終更新** | 2026-05-10 |
| **Status** | Active (Phase 4-1 実装済 / Phase 4-2 ETL 着手予定) |
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
| **Phase 4-1** | knowledge_base/pgvector_store (asyncpg + pgvector 本番) + build_pgvector_pool | 🔶 実装済 (本 PR) |
| Phase 4-2 | etl/ 配下 7 Job (`weekly_crawl` / `monthly_vacancy` / `monthly_stats_compute` / `half_yearly_facility` / `yearly_navi` / `biyearly_admission` / `wayback_backfill`) + Cloud Run Jobs / Cloud Scheduler デプロイ | ⏳ 未着手 |
| Phase 5 | observability (analytics-platform 計装) + monitoring | ⏳ 未着手 |

---

## 3. Phase 4-1 で確定した詳細

### 3.0 設計判断

- **PgvectorStore は `asyncpg.Pool` を外部から受け取る**: クラス内で pool を作らず、consumer 側 (ETL Job / agent main) のライフサイクルでクローズする。短命接続を避けて Cloud SQL の同時接続上限を保護。driving-license-bot の `PgvectorQuestionBank` と同パターン。
- **`pgvector.asyncpg.register_vector` は 1 クエリごとに呼ぶ**: Pool から acquire される接続は再利用されるが、再利用時の register は no-op になる前提で愚直に呼ぶ (driving-license-bot と同方針)。
- **cosine 距離は `<=>` 演算子、類似度は `1 - (<=>)`**: pgvector 標準。HNSW より ivfflat (`lists=100`) を schema で採用済 (proposal §4.3)。
- **asyncpg / pgvector は lazy import**: `[pgvector]` extra なしでも fujisawa-platform を import できるようにする (consumer が in-memory のみ使うケースを許容)。
- **pgvector 単体テストは asyncpg を mock**: 実 Cloud SQL は CI に持たない。proposal §4.6 の通り、接続 smoke は Phase 4-2 ETL デプロイ時に手動。

### 3.1 PgvectorStore の挙動

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

### 3.2 build_pgvector_pool helper

| 観点 | 仕様 |
|---|---|
| 引数 | `host` / `port=5432` / `user` / `password` / `database` / `min_size=1` / `max_size=5` |
| 戻り値 | `asyncpg.Pool` |
| Cloud SQL Auth Proxy | `host="127.0.0.1"` を渡すだけで対応可能 |
| ライフサイクル | 呼出側が `await pool.close()` する (本ライブラリは管理しない) |

実装: 同上 (`pgvector_store.py` 末尾)

### 3.3 Phase 4-2 への引き継ぎ

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

## 4. Phase 3 で確定した詳細

### 4.0 設計判断

- **緊急情報 RSS の 5 分 poll loop は LINE bot 側に置く**: 共通基盤側は `parse_feed(bytes) -> list[RssEntry]` の純粋な parse helper のみ提供する (proposal 0003 §4.5.4 の方針: 「5 分間隔の job が他 consumer にも見えると混乱する」)。LINE bot 側 `fujisawa-info-bot/batch/poll_rss.py` が `seen_guids` セットを Firestore で管理する。
- **`parse_feed` は RSS 2.0 / Atom 両対応**: 藤沢市 HP がどちらを返すか実機未確認のため、両 schema を 1 関数で吸収。`<rss>` / `<feed>` のルート要素で分岐。
- **Wayback クライアントは `PoliteFetcher` を流用しない**: web.archive.org は別ホストで polite ルール (5 秒間隔 / 503 retry) も別。共通化するメリットより独立 client の方が単純。
- **CDX クエリは statuscode != 200 を捨てる**: Wayback には 404 / 301 のスナップショットも履歴として残るが、PDF 取得は不可能のため `_rows_to_snapshots` で除外。
- **Wayback バックフィルは Phase 4 で 1 度きり実行**: 本 PR ではクライアント実装のみ。実データ投入は Phase 4 の `etl/wayback_backfill.py` で `admission_results` (令和 4-6 年) + `competition_stats.historical_minimum_index_2022` に流し込む。

### 4.1 緊急情報 RSS parser (`crawler/rss_poller.py`)

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

### 4.2 Wayback クライアント (`crawler/wayback.py`)

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

### 4.3 Phase 4-2 への引き継ぎ事項

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

## 5. Phase 2 で確定した詳細

### 5.0 設計判断

- **PgvectorStore (本番 asyncpg 実装) は Phase 4 に延期**: Cloud SQL への接続ライフサイクルが ETL Cloud Run Jobs と一体のため、Phase 4 で同時に実装。Phase 2 範囲では Protocol + InMemoryStore (Mock) を提供。
- **Embedding は Protocol + Mock + Vertex の 3 段構成**: driving-license-bot の `app/agent/embedding.py` パターンを踏襲。Vertex は lazy import (`uv sync --extra vertex` で導入)。
- **Docling は完全 lazy import**: `[pdf]` extra として ML deps を分離。Phase 4 ETL でのみ必要。
- **rapidfuzz scorer は `fuzz.ratio` (Levenshtein)**: 日本語は token boundaries が無いため、token-set ratio より文字レベル ratio が中黒 (なかぐろ「・」、例: 「キディ鵠沼・藤沢」⇔「キディ鵠沼藤沢」) / typo に強い。

### 5.1 FacilityResolver の挙動

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

### 5.2 EmbeddingClient の Protocol

| 観点 | 仕様 |
|---|---|
| Protocol | `dimension` プロパティ + `embed(text) -> list[float]` + `embed_batch(texts)` |
| MockEmbeddingClient | SHA-256 ハッシュベースで決定的、L2 正規化済 (cosine = 内積) |
| VertexEmbeddingClient | `text-embedding-004` (768 dim)、認証は Workload Identity、import は lazy |
| 次元 | default 768 (Vertex `text-embedding-004` に合わせる) |

実装: [`fujisawa_platform/knowledge_base/embedding.py`](../fujisawa_platform/knowledge_base/embedding.py)
テスト: 10 ケース PASS

### 5.3 KnowledgeStore (pages テーブル抽象)

| 観点 | 仕様 |
|---|---|
| Protocol | `upsert_page` / `get_page` / `delete_page` / `search_pages` (全部 async) |
| InMemoryStore | dict ベース、cosine = 内積で full scan top-k |
| 検索フィルタ | `category` で絞り込み (将来 region / age_class 等を追加) |
| dimension 検証 | upsert / search 時に embedding 次元が store の `embedding_dim` と一致するか確認 |
| 本番 PgvectorStore | Phase 4 で追加 (本 PR は雛形のみ) |

実装: [`fujisawa_platform/knowledge_base/store.py`](../fujisawa_platform/knowledge_base/store.py)
テスト: 11 ケース PASS

### 5.4 pdf_pipeline の 3 helpers

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

## 6. Phase 1 で確定した詳細

### 6.1 PoliteFetcher の挙動

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

### 6.2 sitemap.xml の parse 仕様

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

### 6.3 Skill File 5 種

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

### 6.4 pgvector schema (8 テーブル)

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

## 7. NFR (proposal 0003 §3 から要約)

| 観点 | 目標 / 制約 |
|---|---|
| 性能 | crawler 1 URL/3s、sitemap 全クロール 1 時間 / pgvector top-10 < 200ms p95 |
| コスト | Cloud SQL instance 共有で月 ¥0 増、Vertex Embedding 月 ¥10 以下 |
| プライバシー | public 情報のみ扱う、PII は consumer 側 |
| 可用性 | sitemap 取得失敗時は旧データ温存 |
| 保守性 | カバレッジ目標 80%、Phase 1 の crawler / skills / db は 90%+ 達成済 |

詳細は proposal 0003 §3 / §5.4 参照。

---

## 8. 関連ドキュメント

- [`../README.md`](../README.md) — Quickstart / 利用方法
- proposal 0003-0005 (上記 §1)
- 事前調査ノート (上記 §1)
- [`fujisawa_platform/skills/`](../fujisawa_platform/skills/) — 共通 SKILL.md 5 種
- [`fujisawa_platform/db/init_schema.sql`](../fujisawa_platform/db/init_schema.sql) — pgvector schema

---

## 9. 用語集

| 用語 | 意味 |
|---|---|
| polite fetcher | UA 明示 + interval + IfMS を強制する礼儀正しい HTTP 取得層 |
| Wayback バックフィル | Internet Archive 経由で過去 PDF を取得する手法 |
| 鮮度メタデータ | `as_of` / `source_url` / `snapshot_date` を含む共通型 (`FreshnessMetadata`) |
| consumer (本基盤の) | path dep で本ライブラリを使う 2 エージェント (info-bot / 保活) |
| etl_role / consumer_role | DB の IAM ロール分離 (proposal 0003 §4.5.3) |
| `historical_minimum_index_2022` | 令和 4 年の最低内定指数。proposal 0005 のハイブリッドモデル用 (M8) |
