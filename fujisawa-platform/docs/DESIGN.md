# fujisawa-platform 設計書

| | |
|---|---|
| **Version** | 0.1 |
| **最終更新** | 2026-05-09 |
| **Status** | Active (Phase 2 実装済 / Phase 3 着手予定) |
| **Owner** | @kurama554101 |
| **Type** | 共通基盤ライブラリ (path dep として info-bot / 保活 から参照) |
| **README** | [`../README.md`](../README.md) |

## 変更履歴

| 日付 | Version | 変更内容 |
|---|---|---|
| 2026-05-09 | 0.1 | 初版 (Phase 1: パッケージ雛形 + crawler + skills + DB schema) |
| 2026-05-09 | 0.2 | Phase 2 実装 (resolver / knowledge_base + Mock backends / pdf_pipeline) |

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
| **Phase 2** | resolver (FacilityResolver) + knowledge_base (Embedding Protocol + Mock + Vertex / KnowledgeStore Protocol + InMemoryStore) + pdf_pipeline (hash_diff / freshness / docling lazy) | 🔶 実装済 (本 PR) |
| Phase 3 | crawler/rss_poller + crawler/wayback | ⏳ 未着手 |
| Phase 4 | knowledge_base/pgvector_impl (asyncpg 本番) + etl/ 配下 7 Job + Cloud Run Jobs デプロイ | ⏳ 未着手 |
| Phase 5 | observability (analytics-platform 計装) + monitoring | ⏳ 未着手 |

---

## 3. Phase 2 で確定した詳細

### 3.0 設計判断

- **PgvectorStore (本番 asyncpg 実装) は Phase 4 に延期**: Cloud SQL への接続ライフサイクルが ETL Cloud Run Jobs と一体のため、Phase 4 で同時に実装。Phase 2 範囲では Protocol + InMemoryStore (Mock) を提供。
- **Embedding は Protocol + Mock + Vertex の 3 段構成**: driving-license-bot の `app/agent/embedding.py` パターンを踏襲。Vertex は lazy import (`uv sync --extra vertex` で導入)。
- **Docling は完全 lazy import**: `[pdf]` extra として ML deps を分離。Phase 4 ETL でのみ必要。
- **rapidfuzz scorer は `fuzz.ratio` (Levenshtein)**: 日本語は token boundaries が無いため、token-set ratio より文字レベル ratio が中黒 / typo に強い。

### 3.1 FacilityResolver の挙動

| 観点 | 仕様 |
|---|---|
| 入力 | `query` (検索文字列) + `entries` (ResolverEntry のリスト) |
| 解決経路 | 1. canonical / alias 完全一致 (score=1.0) 2. fuzz.ratio で fuzzy match |
| threshold | default 0.85 (中黒 / 軽微 typo を吸収) |
| `resolve()` | 最高スコアを 1 つ返す。threshold 未満は `NoMatchError` |
| `resolve_all(top_k)` | score 降順で top-k。同 facility_id は最高スコアのみ |
| 重複排除 | canonical と alias 両方にヒットしても 1 件にまとめる |

実装: [`fujisawa_platform/resolver/facility_resolver.py`](../fujisawa_platform/resolver/facility_resolver.py)
テスト: 13 ケース PASS

### 3.2 EmbeddingClient の Protocol

| 観点 | 仕様 |
|---|---|
| Protocol | `dimension` プロパティ + `embed(text) -> list[float]` + `embed_batch(texts)` |
| MockEmbeddingClient | SHA-256 ハッシュベースで決定的、L2 正規化済 (cosine = 内積) |
| VertexEmbeddingClient | `text-embedding-004` (768 dim)、認証は Workload Identity、import は lazy |
| 次元 | default 768 (Vertex `text-embedding-004` に合わせる) |

実装: [`fujisawa_platform/knowledge_base/embedding.py`](../fujisawa_platform/knowledge_base/embedding.py)
テスト: 10 ケース PASS

### 3.3 KnowledgeStore (pages テーブル抽象)

| 観点 | 仕様 |
|---|---|
| Protocol | `upsert_page` / `get_page` / `delete_page` / `search_pages` (全部 async) |
| InMemoryStore | dict ベース、cosine = 内積で full scan top-k |
| 検索フィルタ | `category` で絞り込み (将来 region / age_class 等を追加) |
| dimension 検証 | upsert / search 時に embedding 次元が store の `embedding_dim` と一致するか確認 |
| 本番 PgvectorStore | Phase 4 で追加 (本 PR は雛形のみ) |

実装: [`fujisawa_platform/knowledge_base/store.py`](../fujisawa_platform/knowledge_base/store.py)
テスト: 11 ケース PASS

### 3.4 pdf_pipeline の 3 helpers

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

## 4. Phase 1 で確定した詳細

### 4.1 PoliteFetcher の挙動

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

### 4.2 sitemap.xml の parse 仕様

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

### 4.3 Skill File 5 種

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

### 4.4 pgvector schema (8 テーブル)

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

## 5. NFR (proposal 0003 §3 から要約)

| 観点 | 目標 / 制約 |
|---|---|
| 性能 | crawler 1 URL/3s、sitemap 全クロール 1 時間 / pgvector top-10 < 200ms p95 |
| コスト | Cloud SQL instance 共有で月 ¥0 増、Vertex Embedding 月 ¥10 以下 |
| プライバシー | public 情報のみ扱う、PII は consumer 側 |
| 可用性 | sitemap 取得失敗時は旧データ温存 |
| 保守性 | カバレッジ目標 80%、Phase 1 の crawler / skills / db は 90%+ 達成済 |

詳細は proposal 0003 §3 / §5.4 参照。

---

## 6. 関連ドキュメント

- [`../README.md`](../README.md) — Quickstart / 利用方法
- proposal 0003-0005 (上記 §1)
- 事前調査ノート (上記 §1)
- [`fujisawa_platform/skills/`](../fujisawa_platform/skills/) — 共通 SKILL.md 5 種
- [`fujisawa_platform/db/init_schema.sql`](../fujisawa_platform/db/init_schema.sql) — pgvector schema

---

## 7. 用語集

| 用語 | 意味 |
|---|---|
| polite fetcher | UA 明示 + interval + IfMS を強制する礼儀正しい HTTP 取得層 |
| Wayback バックフィル | Internet Archive 経由で過去 PDF を取得する手法 |
| 鮮度メタデータ | `as_of` / `source_url` / `snapshot_date` を含む共通型 (`FreshnessMetadata`) |
| consumer (本基盤の) | path dep で本ライブラリを使う 2 エージェント (info-bot / 保活) |
| etl_role / consumer_role | DB の IAM ロール分離 (proposal 0003 §4.5.3) |
| `historical_minimum_index_2022` | 令和 4 年の最低内定指数。proposal 0005 のハイブリッドモデル用 (M8) |
