# fujisawa-platform 設計書

| | |
|---|---|
| **Version** | 0.12 |
| **最終更新** | 2026-05-12 |
| **Status** | Active (Phase 4-2h step 1-3 全実装済、配備可能状態 / 残: terraform CI 化は Phase 4-2h step 4 で別途) |
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
| 2026-05-11 | 0.7 | Phase 4-2c 実装 (biyearly_admission_etl + AdmissionRepo + admission_parser + pdf_pipeline.extract_tables) |
| 2026-05-11 | 0.7.1 | Phase 4-2c-2 補強 (PdfArchive Protocol + GcsArchive / LocalArchive / NullArchive、biyearly_admission に統合) |
| 2026-05-11 | 0.8 | Phase 4-2d 実装 (monthly_vacancy_etl + VacancyRepo + ApplicationRepo + vacancy_parser、PdfArchive 初期 DI) |
| 2026-05-11 | 0.9 | Phase 4-2e 実装 (yearly_navi_etl + PdfDocumentsRepo、申込ナビ PDF chunk 化 + embedding、PdfArchive 初期 DI) |
| 2026-05-12 | 0.10 | Phase 4-2f 実装 (monthly_stats_compute + CompetitionStatsRepo + stats_compute、外部 fetch なし) |
| 2026-05-12 | 0.11 | Phase 4-2g 実装 (wayback_backfill + min_index_parser、Wayback 経由で令和 4-6 年 PDF をバックフィル) |
| 2026-05-12 | 0.11.1 | Phase 4-2h step 1 実装 (etl/cli.py + Dockerfile + docs/SETUP.md、Cloud Run Job entrypoint と配備 runbook) |
| 2026-05-12 | 0.11.2 | Phase 4-2h step 2 実装 (terraform: Cloud SQL DB / Secret Manager / IAM / GCS bucket / Artifact Registry) |
| 2026-05-12 | 0.12 | Phase 4-2h step 3 実装 (terraform: Cloud Run Jobs × 7 + Cloud Scheduler × 6、配備可能状態) |
| 2026-05-21 | 0.13 | `weekly_crawl_etl` 差分 crawl 化 (HEAD で Last-Modified 比較 → 更新有り URL のみ GET)。 sitemap 規模が想定 1,100 URL → 実測 7,906 URL で task timeout 内に完走不能だったため。 polite_fetcher に `head()` 追加、 `_runner.py` に orphan running reclassify 追加、 task_timeout 5400→28800 秒。 proposal §4.5.4 更新。 |

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
| **Phase 4-2b** | `half_yearly_facility_etl` + `FacilitiesRepo` + `facility_parser` + `_html_table` | ✅ 完了 (PR #121) |
| **Phase 4-2c** | `biyearly_admission_etl` + `AdmissionRepo` + `admission_parser` + `pdf_pipeline.extract_tables` + `build_facility_resolver` | ✅ 完了 (PR #122) |
| **Phase 4-2c-2** | `PdfArchive` Protocol + `GcsArchive` / `LocalArchive` / `NullArchive` + `biyearly_admission_etl` 統合 (proposal §4.5 line 204 の実装漏れ補強) | ✅ 完了 (PR #123) |
| **Phase 4-2d** | `monthly_vacancy_etl` + `VacancyRepo` / `ApplicationRepo` + `vacancy_parser` (PdfArchive を初期 DI) | ✅ 完了 (PR #124) |
| **Phase 4-2e** | `yearly_navi_etl` + `PdfDocumentsRepo` (申込ナビ PDF chunk 化 + embedding、PdfArchive 初期 DI) | ✅ 完了 (PR #125) |
| **Phase 4-2f** | `monthly_stats_compute` + `CompetitionStatsRepo` + `stats_compute` (DB 内集計のみ、外部 fetch なし) | ✅ 完了 (PR #126) |
| **Phase 4-2g** | `wayback_backfill` + `min_index_parser` (Wayback 経由で令和 4-6 年 PDF をバックフィル、一度きり実行) | ✅ 完了 (PR #127) |
| **Phase 4-2h step 1** | `etl/cli.py` (Job dispatcher) + `Dockerfile` + `docs/SETUP.md` (GCP 構築 runbook) | ✅ 完了 (PR #129) |
| **Phase 4-2h step 2** | terraform: Cloud SQL DB / Secret Manager / IAM / Artifact Registry / GCS bucket | ✅ 完了 (PR #130) |
| **Phase 4-2h step 3** | terraform: Cloud Run Jobs × 7 + Cloud Scheduler × 6 | 🔶 実装済 (本 PR) |
| Phase 4-2h step 4 (任意) | CI で terraform plan / 静的解析 (tflint / tfsec) | ⏳ 後回し可 |
| Phase 5 | observability (analytics-platform 計装) + monitoring | ⏳ 未着手 |

---

## 2.5. Phase 5 (weekly_crawl 差分 crawl 化) で確定した詳細 (2026-05-21)

> proposal 0003 §4.5.4 v2 / §8 Implementation History 2026-05-21 を実装した記録。

### 2.5.0 設計判断

- **sitemap 規模見積りの是正**: proposal §3.2 で "1,100+ URL" としていた sitemap が、
  2026-05 計測で **7,906 URL** に増えていた。 旧 weekly_crawl は GET 3 秒/URL × 7906 = 6.6 時間
  必要で Cloud Run task timeout 90 分内に完走不可。 2026-05-16 の自動実行が 1,797 URL
  処理時点で timeout し、 stale な `running` レコードが残っていた。
- **HEAD + Last-Modified 差分判定を採用**: 藤沢市サーバーは全ページで HTTP `Last-Modified`
  を正常に返すことを実測で確認 (例: `/index.html` 2026-05-20, `/hoiku/.../ninka-ichiran.html`
  2026-05-12, `/bosai/shobo/tsuho/index.html` 2025-09-30)。 sitemap.xml に `<lastmod>` は
  含まれないため、 lastmod ベースの差分は使えないが、 HEAD で代替可能と判明。
- **HEAD は GET より polite rate を短く (0.5 秒) する**: ボディ転送無しでサーバー負荷が
  GET の数十分の 1 のため、 1 秒間隔まで縮めるのは合理的。 7,906 × 0.5s = 66 分で全件 HEAD 可。
- **ETag は使わない**: Last-Modified だけで十分な精度。 ETag 併用は DB スキーマ拡張 +
  両方一致判定ロジックの複雑化が必要で割に合わない。 サーバーの時計調整やキャッシュの
  誤動作で偽差分が出る程度のリスクは許容範囲。
- **初回 / 大幅更新時は HEAD スキップ + 全件 GET fallback**: DB が空 or `last_modified`
  カラムが NULL の URL は HEAD を打たずに即 GET。 これで「初回 7,906 × 3s = 6.6 時間 +
  HEAD 1 時間 = 7.6 時間」 を「初回 6.6 時間のみ」 に短縮。 task_timeout 8 時間に拡張して吸収。
- **orphan `running` レコードの自動 reclassify**: Cloud Run task timeout で強制終了されると
  `finish_run` が呼ばれず `running` のまま残る (2026-05-16 が実例)。 `run_etl_job` の start
  時に 12 時間超の `running` を `aborted` に reclassify する保守ロジックを追加。

### 2.5.1 `polite_fetcher.head()` の挙動

| API | 用途 |
|---|---|
| `PoliteFetcher.head(url)` | 1 URL に HEAD を打って `HeadResult (status, last_modified, etag)` を返す。 4xx は raise、 5xx は retry。 |
| `PoliteFetcherConfig.min_interval_sec_head` | HEAD 専用 polite rate (default 0.5 秒)。 `min_interval_sec` (GET 用、 3 秒 default) と独立。 |
| `_last_head_at` / `_last_fetch_at` | 内部状態。 HEAD と GET の rate limiter を別々に持つ。 |

### 2.5.2 `weekly_crawl.crawl_and_index()` のフロー

```
1. fetcher.fetch(sitemap_url)              # GET (1 回、 1 KB)
2. parse_sitemap → list[entry]
3. store.get_last_modified_map(urls)       # SELECT WHERE url = ANY($1) (1 クエリ)
4. for each URL:
   ├─ DB に row 無い → GET 対象 (HEAD スキップ)
   ├─ DB last_modified NULL → GET 対象 (HEAD スキップ、 保守的)
   └─ DB last_modified 有り:
       └─ fetcher.head(url)
           ├─ サーバー側 Last-Modified > DB 値 → GET 対象
           ├─ Last-Modified 不在 → GET 対象 (保守的)
           ├─ HEAD 4xx/5xx → GET 対象 (fallback)
           └─ それ以外 → skip_unchanged
5. GET 対象だけ fetcher.fetch(url) → extract_main_text → embed → upsert
```

### 2.5.3 `CrawlOutcome` 新フィールド

| フィールド | 用途 |
|---|---|
| `skipped_unchanged` | HEAD 比較で skip した URL 数 (通常運用で最も多い) |
| `head_checks` | HEAD を打った URL 数 (HEAD コスト計測用) |
| `skipped_not_modified` | GET の 304 で skip した URL 数 (差分 crawl では原則 0、 保険用に残す) |

### 2.5.4 `_runner.run_etl_job` の orphan reclassify

start_run 直前に以下を実行:

```python
await repo.abort_stale_running(
    job_name=job_name,
    now=started_at,
    stale_after_hours=12,  # _STALE_RUNNING_HOURS
)
```

`AttributeError` (古い repo / mock) は graceful に握りつぶす。 既存テストとの互換性を保つ。

`etl_runs.status` のドメイン値に `aborted` を追加 (SQL は `TEXT NOT NULL` のため schema 変更不要、 コメントのみ更新)。 `aborted` は `failed` とは別物として扱うため、 fail-fast 判定 (5 連敗) には**カウントしない**。

### 2.5.5 terraform 変更

| 変数 | 旧 | 新 | 用途 |
|---|---|---|---|
| `etl_job_task_timeout_seconds` | 5400 | **28800** | 初回 full crawl (6.6 時間) を吸収する 8 時間 |
| `etl_min_interval_sec` (新規) | — | 3.0 | GET 用 polite rate (env: `FUJISAWA_ETL_MIN_INTERVAL_SEC`) |
| `etl_min_interval_sec_head` (新規) | — | 0.5 | HEAD 用 polite rate (env: `FUJISAWA_ETL_MIN_INTERVAL_SEC_HEAD`) |

通常週次の Job 実行時間は HEAD ~1 時間 + GET 数百件 (15-30 分) = 1.5 時間程度に収まるため、 timeout 8 時間でもコスト増は無視できる (Cloud Run は実行時間ベース課金)。

### 2.5.6 既知の制約 / 残課題

- 2026-05-16 の orphan `running` レコードは次回 Job 実行時に自動 reclassify される (本 PR のロジックが効く)
- 既に書き込まれていた 1,681 行 (2026-05-16 partial run の成果物) はそのまま残る — last_modified カラムが入っているため、 次回 weekly_crawl で重複 GET にはならない
- proposal §4.6 の Test Plan には差分 crawl の挙動テストが含まれていなかったので、 本 PR で追加した tests/etl/test_weekly_crawl.py の `TestCrawlAndIndexIncremental` クラスを補強テストとして扱う

---

## 3. Phase 4-2g で確定した詳細

### 3.0 設計判断

- **一度きり実行を想定した Job**: proposal §4.5.4 表の「一度きり (Phase 0)」に対応。`FUJISAWA_ETL_WAYBACK_BACKFILL_ENABLED` は default false で、明示的に on にしないと動かない (config 既存)。
- **複数 PDF を 1 Job 内で順次処理**: 令和 4-6 年の PDF を `BackfillItem` のリストで渡して、順に Wayback fetch → archive → parse → in-memory merge → DB upsert。WaybackClient の polite ルール (5 秒間隔 + 503 retry) は内部で守られる。
- **2 種類の parser をハイブリッドで適用**: `BackfillItem.kind`
  - `'regular'`: 通常の入所結果 PDF (令和 5-6 年含む) → `parse_admission_table` (Phase 4-2c 既存)
  - `'min_index_2022'`: 令和 4 年最低指数 PDF → 新規 `parse_min_index_table` (本 PR で追加)
- **in-memory merge で None 上書きを回避**: `regular` PDF は `applicants/capacity/vacancy_after` を、`min_index_2022` PDF は `min_*` 4 フィールドを別々の PDF から提供する。同じ (facility, year, round, age_class) で merge することで、片方の PDF にしか値がないフィールドが他方の None で上書きされない。
- **PdfArchive を最初から DI**: Phase 4-2c-2 の方針通り。`archive_path` は `wayback_backfill/{year}/{round}/{sha256[:16]}-{filename}.pdf`。Wayback 経由でしか取れない PDF こそ自前で原本を残す価値が高い。
- **`fetch_bytes(archive_url)` で URL ベース取得**: WaybackClient の `fetch_archive(WaybackSnapshot)` は snapshot オブジェクト要求だが、本 Job は archive URL を直接組み立てるので、内部 `_get_bytes_with_retry` をラップする `_WaybackBytesAdapter` で URL を直接受け取れるよう橋渡し。
- **`wayback_factory` DI**: テストで実 HTTP を叩かないよう、`async with` 互換のクライアント生成関数を差し替え可能。

### 3.1 `min_index_parser` (`etl/min_index_parser.py`)

| 観点 | 仕様 |
|---|---|
| 関数 | `parse_min_index_table(*, table, source_pdf_url, resolver) -> list[MinIndexEntry]` |
| `MinIndexEntry` | `facility_id` / `age_class` / `basic` / `priority` / `coord` / `notation` / `source_pdf_url` |
| セル parse | 既存 `admission_parser.parse_min_index_notation` を再利用 (Phase 4-2c で同梱済) |
| skip 条件 | マーカー (`△` / `○` / `-` / `＼`) / 空文字 / 不正フォーマット / resolver 不一致 |

実装: [`fujisawa_platform/etl/min_index_parser.py`](../fujisawa_platform/etl/min_index_parser.py)
テスト: 7 ケース PASS

### 3.2 `wayback_backfill_etl` (`etl/wayback_backfill.py`)

| 観点 | 仕様 |
|---|---|
| 起動 | `run_wayback_backfill(*, items, wayback_config, admission_repo, runs_repo, resolver, run_id, archive=None, wayback_factory=None, ...)` |
| `BackfillItem` | `kind` ('regular' \| 'min_index_2022') + `wayback_timestamp` + `original_url` + `year` + `round` |
| 処理 | item ごとに Wayback fetch → archive.put → extract_tables → kind 別 parser → in-memory merge |
| マージキー | `(facility_id, year, round, age_class)` |
| マージ規則 | regular は `applicants/capacity/vacancy_after/source_pdf_url/as_of` を更新、min_index_2022 は `min_*` 4 フィールドを更新 (他フィールドは保持) |
| upsert | 全 PDF 処理後にまとめて `admission_repo.upsert_many` |
| dry_run | parse / archive は実行、upsert はスキップ |
| `wayback_factory` DI | 本番は `_default_wayback_factory` (実 WaybackClient + Bytes アダプタ)、テストは fake を注入 |

実装: [`fujisawa_platform/etl/wayback_backfill.py`](../fujisawa_platform/etl/wayback_backfill.py)
テスト: 11 ケース PASS

### 3.3 `competition_stats.historical_minimum_index_2022` への反映経路

本 Job は `admission_results.min_*` 4 フィールドを埋めるところまで担当。
**`competition_stats.historical_minimum_index_2022` の更新は `monthly_stats_compute` (Phase 4-2f) が次回実行時に行う** (proposal §4.5.4 表で「集計は外部 fetch なしの monthly Job」と明記されているため)。

すなわち手順は:
1. Phase 4-2g `wayback_backfill` を **一度実行** → `admission_results` に令和 4 年 min_* 4 項目が入る
2. その後 Phase 4-2f `monthly_stats_compute` が走る (月次) → `historical_minimum_index_2022` JSONB が埋まる

### 3.4 Phase 4-2 機能 Job 完了 (4-2h 残)

本 PR で 7 種類の ETL Job (定期 6 + 一度きり 1) と全 Repo (etl_runs / facilities / vacancy / application / admission / pdf_documents / competition_stats) + 全 parser が揃いました。残るは:

- **Phase 4-2h**: terraform (Cloud Run Jobs / Cloud Scheduler / Secret Manager / IAM 設定) のみ

---

## 4. Phase 4-2f で確定した詳細

### 4.0 設計判断

- **外部 fetch なしの DB-only Job**: proposal §4.5.4 の表で「外部 fetch なし」と明記。`admission_results` を読んで集計し `competition_stats` を更新するだけ。`PoliteFetcher` / `PdfArchive` / Docling は不要。
- **集計ロジックは pure 関数 (`stats_compute.py`) に分離**: DB 接続なしで全パターンを単体テスト可能。ETL Job (`monthly_stats_compute.py`) は DB I/O + グループ化のみ。proposal 0005 §9.5 / 調査ノート §A2-2 のハイブリッドモデルに準拠。
- **直近 3 年分のみ avg を計算、history は全年保持**: `current_year - 2 .. current_year` の 3 年で avg_ratio_3y を出すが、`history` JSONB には取得できた全年を残す (保活 StrategyAgent が過去倍率トレンドを参照できるように)。
- **1 次のみ集計対象**: 2 次入所結果は集計から除外。1 次の applicants_at_deadline が「実質の競争度」を表す数字。
- **competition_level の閾値**: 倍率 2.0 以上 → 超人気 / 1.0 以上 → 人気 / 1.0 未満 → 比較的入りやすい / データなし → data_unavailable。
- **trend の閾値**: 最古 vs 最新 ratio を比較し ±10% で rising / declining / stable。データ 2 点未満は None。
- **confidence の閾値**: 有効データ年数 → 3+ high / 2 medium / 1 low / 0 unknown。
- **historical_minimum_index_2022 の抽出条件**: 令和 4 年レコードに `min_basic_score` / `min_priority` / `min_coordination_score` / `min_index_notation` の **4 項目すべて** が揃っているときのみ。

### 4.1 `CompetitionStatsRepo` (`etl/_repos/competition_stats.py`)

| 観点 | 仕様 |
|---|---|
| PK | `(facility_id, age_class)` |
| `upsert_many()` | 行ごとに `INSERT ... ON CONFLICT DO UPDATE`、空 list は no-op |
| `count()` | 全件数 (smoke / 監視) |
| JSONB | `history` / `historical_minimum_index_2022` / `based_on` は `json.dumps(..., ensure_ascii=False)` で `::jsonb` cast |
| Pydantic 検証 | `competition_level` / `trend` / `confidence` の列挙値、`age_class` 0-5、`priority` 単一英大文字 (A〜K のうち H なし) |

実装: [`fujisawa_platform/etl/_repos/competition_stats.py`](../fujisawa_platform/etl/_repos/competition_stats.py)
テスト: 13 ケース PASS

### 4.2 `stats_compute` (`etl/stats_compute.py`、pure 関数)

| 関数 | 用途 |
|---|---|
| `classify_level(ratio)` | 倍率 → '超人気' / '人気' / '比較的入りやすい' / 'data_unavailable' |
| `classify_trend(ratios)` | 古い→新しい ratio 列 → 'rising' / 'stable' / 'declining' / None |
| `confidence_from_years(years)` | 有効年数 → 'high' / 'medium' / 'low' / 'unknown' |
| `compute_competition_stats(*, facility_id, age_class, admissions, now)` | 1 (facility, age_class) → `CompetitionStatsRecord` |
| 1 次のみ集計 | round='2nd' は除外 |
| based_on 重複排除 | 同じ source_pdf_url は 1 回だけ含める |
| historical_minimum_index_2022 | 令和 4 年レコードに min_* 4 項目揃っていれば抽出 |

実装: [`fujisawa_platform/etl/stats_compute.py`](../fujisawa_platform/etl/stats_compute.py)
テスト: 27 ケース PASS

### 4.3 `AdmissionRepo.list_recent_years()` 追加

| 観点 | 仕様 |
|---|---|
| シグネチャ | `list_recent_years(*, min_year, max_year)` |
| SQL | `WHERE year BETWEEN $1 AND $2 ORDER BY facility_id, age_class, year` |
| 用途 | Phase 4-2f の集計 Job が 3 年分を読み出す入力 |

### 4.4 `monthly_stats_compute` (`etl/monthly_stats_compute.py`)

| 観点 | 仕様 |
|---|---|
| 起動 | `run_monthly_stats_compute(*, admission_repo, stats_repo, runs_repo, run_id, current_year, ...)` |
| 処理 | `list_recent_years` → `(facility_id, age_class)` グルーピング → `compute_competition_stats` → `upsert_many` |
| 外部 fetch | なし。`PoliteFetcher` / `PdfArchive` / `Docling` を一切呼ばない |
| dry_run | 集計は行うが `stats_repo.upsert_many` を呼ばない |
| source_hash | None (外部 fetch なしのため) |

実装: [`fujisawa_platform/etl/monthly_stats_compute.py`](../fujisawa_platform/etl/monthly_stats_compute.py)
テスト: 6 ケース PASS

---

## 5. Phase 4-2e で確定した詳細

### 5.0 設計判断

- **`extract_chunks` (Phase 2 既存) を再利用**: 申込ナビ PDF は表ではなく **解説文章** なので、`extract_tables` ではなく既存の `extract_chunks` (章別分割) を使う。table 抽出と chunk 抽出は別経路。
- **PK `(pdf_id, chunk_index)` の全置換戦略**: Docling で章別 chunk 化する都合上、chunk_index は再 run のたびに変動しうる (見出し追加で全 chunk がズレる)。**`pdf_id` 単位で DELETE + INSERT を 1 トランザクション** で行うのが安全 (proposal §4.5.5)。
- **pdf_id は URL の SHA-256**: schema コメント (`pdf_id TEXT NOT NULL -- url の SHA-256 hash`) と一致。同じ申込ナビ URL からは常に同じ pdf_id が生成される。
- **PdfArchive を最初から DI**: Phase 4-2c-2 で導入した DI を 4-2e でも採用。default は `NullArchive`、本番 `GcsArchive`、smoke `LocalArchive`。
- **chunk 0 件でも replace は実行**: 古い chunk を残さないため。例えば PDF 構造が変わって Docling が拾えなかった場合も既存 chunk を全削除する (古い chunk が「現在の PDF にある」と誤認される事故を避ける)。
- **`chunk_extractor` DI**: Docling を呼ばないテストを可能にする。既存 `pdf_pipeline.extract_chunks` がデフォルト。

### 5.1 `PdfDocumentsRepo` (`etl/_repos/pdf_documents.py`)

| 観点 | 仕様 |
|---|---|
| PK | `(pdf_id, chunk_index)` |
| `replace_for_pdf(*, pdf_id, records)` | `DELETE WHERE pdf_id = $1` → `INSERT × N` を 1 トランザクション。0 件でも DELETE は実行 |
| `count(pdf_id=?)` | pdf_id 別 / 全体の chunk 数 (smoke / 監視) |
| `chunk_text` 必須 | 空文字は構築段階で ValueError |
| `chunk_index` | 非負整数のみ |
| pgvector | `register_vector` を毎クエリ呼出 (PgvectorStore と同パターン) |

実装: [`fujisawa_platform/etl/_repos/pdf_documents.py`](../fujisawa_platform/etl/_repos/pdf_documents.py)
テスト: 8 ケース PASS

### 5.2 `yearly_navi_etl` (`etl/yearly_navi.py`)

| 観点 | 仕様 |
|---|---|
| 起動 | `run_yearly_navi(*, pdf_url, year, fetcher_config, docs_repo, runs_repo, embedder, run_id, archive=None, chunk_extractor=None, ...)` |
| 処理 | PoliteFetcher PDF fetch → `archive.put` → `extract_chunks` → embedding → `replace_for_pdf` |
| `archive_path` | `yearly_navi_etl/{year}/{sha256[:16]}-{filename}.pdf` (round 列なし) |
| chunk_extractor DI | テストでは Docling を呼ばない mock を注入可能 |
| dry_run | archive + parse は実行、`repo.replace_for_pdf` を呼ばない |
| 0 chunk の挙動 | `repo.replace_for_pdf(records=[])` を呼んで古い chunk を消す |
| source_hash | PDF bytes SHA-256 (前回と一致なら次回 skip-unchanged) |

実装: [`fujisawa_platform/etl/yearly_navi.py`](../fujisawa_platform/etl/yearly_navi.py)
テスト: 7 ケース PASS

### 5.3 `EtlConfig` 拡張

| env | 用途 |
|---|---|
| `FUJISAWA_ETL_NAVI_PDF_URL` | 申込ナビ PDF URL |
| `FUJISAWA_ETL_NAVI_YEAR` | 対象年度 (西暦、default 2026) |

### 5.4 補足: 規則 YAML は本 Job の対象外

proposal §4.5.4 で言及されている `rules/reiwa{N}/*.yaml` は **手動更新** 経路 (本 Job では扱わない)。申込ナビ PDF を RAG で参照可能にするのが本 Job のスコープ。

---

## 6. Phase 4-2d で確定した詳細

### 6.0 設計判断

- **空き状況 + 申込状況 を 1 Job 内で同時に処理**: proposal §4.5.4 で `monthly_vacancy_etl` が両 PDF を扱うと明記。2 PDF を順に fetch → archive → parse → upsert する。Job として 1 つにまとめることで、両テーブルの year_month が必ず揃う (片方だけ run しない)。
- **PK は `(facility_id, year_month, age_class)`**: month 単位の冪等な UPSERT。partial insert 中も既存月の整合性は維持 (proposal §4.5.5)。
- **`PdfArchive` を最初から DI**: Phase 4-2c-2 で導入したアーカイブを初期実装で噛ませる。空き状況と申込状況の **両 PDF を別々に archive.put** (パスは `{year}/{month}/vacancy` と `{year}/{month}/application` で分離)。
- **`year_month: 'YYYY-MM'` で厳格 validation**: pydantic Field validator で 4桁年 + ハイフン + 01-12 月のみ許容。`'2026-13'` や `'2026/04'` は構築時に ValueError。
- **PDF 取得失敗の挙動**: 個別 fetch 失敗 (`httpx.HTTPStatusError`) は上位に伝搬 → `run_etl_job` ラッパー側で `failed` 扱い。両 PDF のうち片方だけ成功してもう片方失敗、というケースは想定しない (両方そろって初めて意味のあるスナップショット)。
- **空セル / `-` / 負数を skip**: 空き 0 件と「該当 age_class なし」は意味が違うので、空セルは age_class スキップ。負数も無効値扱い。

### 6.1 `VacancyRepo` + `ApplicationRepo` (`etl/_repos/vacancy.py`)

| Repo | テーブル | PK | UPSERT 戦略 |
|---|---|---|---|
| `VacancyRepo` | `vacancy_snapshots` | `(facility_id, year_month, age_class)` | 行ごとに `INSERT ON CONFLICT DO UPDATE`、0 件は no-op |
| `ApplicationRepo` | `application_snapshots` | 同上 | 同上 |
| `count(year_month=?)` | 両方 | - | 月別件数 (smoke / 監視用) |

実装: [`fujisawa_platform/etl/_repos/vacancy.py`](../fujisawa_platform/etl/_repos/vacancy.py)
テスト: 16 ケース PASS

### 6.2 `vacancy_parser` (`etl/vacancy_parser.py`)

| 関数 | 用途 |
|---|---|
| `parse_vacancy_table(*, table, year_month, snapshot_date, source_pdf_url, fetched_at, resolver)` | 空き状況 PDF 表 → `list[VacancySnapshotRecord]`。施設名列 + `<N>歳児` カラム検出 |
| `parse_application_table(*, ...)` | 申込状況 PDF 表 → `list[ApplicationSnapshotRecord]`。施設名列 + `<N>歳児定員` + `<N>歳児申込` の 2 カラム検出 |
| skip 条件 | 空セル / `-` / 負数 / `NoMatchError` (resolver 不一致) は当該 age_class または行を skip |

実装: [`fujisawa_platform/etl/vacancy_parser.py`](../fujisawa_platform/etl/vacancy_parser.py)
テスト: 9 ケース PASS

### 6.3 `monthly_vacancy_etl` (`etl/monthly_vacancy.py`)

| 観点 | 仕様 |
|---|---|
| 起動 | `run_monthly_vacancy(*, vacancy_pdf_url, application_pdf_url, year_month, snapshot_date, ...)` |
| 処理順 | (1) vacancy fetch → archive.put → parse → upsert、(2) application fetch → archive.put → parse → upsert |
| PdfArchive DI | default は `NullArchive`、本番は `GcsArchive`、smoke は `LocalArchive` |
| archive_path | `monthly_vacancy_etl/{year}/{month}/vacancy/<digest>-<filename>.pdf` と `.../application/...` で分離 |
| `MonthlyVacancyOutcome` | `vacancy_rows_written` / `application_rows_written` / `vacancy_archive_path` / `application_archive_path` / 両 PDF hash |
| dry_run | parse + archive は実行、`repo.upsert_many` は呼ばない |
| source_hash | 両 PDF SHA-256 を合成 (どちらかでも変われば run する) |

実装: [`fujisawa_platform/etl/monthly_vacancy.py`](../fujisawa_platform/etl/monthly_vacancy.py)
テスト: 7 ケース PASS

### 6.4 `EtlConfig` 拡張

| env | 用途 |
|---|---|
| `FUJISAWA_ETL_VACANCY_PDF_URL` | 空き状況 PDF URL |
| `FUJISAWA_ETL_APPLICATION_PDF_URL` | 申込状況 PDF URL |
| `FUJISAWA_ETL_VACANCY_YEAR_MONTH` | 対象年月 (`'YYYY-MM'`) |

---

## 7. Phase 4-2c-2 で確定した詳細

### 7.0 設計判断

- **PDF オリジナルバイトの一次保存が抜けていた問題への補強**: Phase 4-2c までは PoliteFetcher で取った PDF を parse 後に破棄していたが、proposal §4.5 line 204 は `fujisawa-raw` / `fujisawa-pdf-archive` への GCS 保存を明記。本 PR で `PdfArchive` Protocol + 3 実装 (`GcsArchive` / `LocalArchive` / `NullArchive`) を追加し、`biyearly_admission_etl` に統合。
- **Protocol で 3 backend を切り替え可能に**: ETL Job は `archive: PdfArchive` を DI で受け取り、本番は `GcsArchive`、smoke は `LocalArchive`、Phase 0 の段階導入時は `NullArchive` (no-op) に切り替えられる。新規 Job (4-2d / 4-2e / 4-2g) は **デフォルトでこの DI を持つ前提で実装する**。
- **archive_path() は決定的**: `{job}/{year}/{round}/{sha256[:16]}-{filename}.pdf` 形式。同じ URL は常に同じパスに保存される (再 run で重複アップロード防止)。
- **path traversal は LocalArchive で拒否**: `../escape.pdf` のような相対パスは `_resolve_inside_root` が `relative_to(root)` で検証し ValueError。
- **archive は dry_run でも実行**: DB upsert を skip しても **原本保存は出典担保のため必ず行う**。Cloud Run Job デプロイ前の手動 smoke でアーカイブ確認できるメリットもある。
- **`google-cloud-storage` は `[gcs]` extra**: ETL Cloud Run Job のみ必要なので、consumer (LINE bot / 保活) には噛ませない。

### 7.1 `PdfArchive` Protocol + 3 実装

| 実装 | 用途 | 依存 |
|---|---|---|
| `GcsArchive` | 本番 (`fujisawa-pdf-archive` バケット) | `google-cloud-storage` lazy import |
| `LocalArchive` | dev / smoke / テスト | 標準ライブラリのみ |
| `NullArchive` | Phase 0 アーカイブ無効化 | なし |

メソッド: `put(path, content, source_url, fetched_at)` / `get(path)` / `exists(path)`

実装: [`fujisawa_platform/etl/pdf_archive.py`](../fujisawa_platform/etl/pdf_archive.py)
テスト: 24 ケース PASS (PdfArchive 18 + GcsArchive 6)

### 7.2 `archive_path()`

| 観点 | 仕様 |
|---|---|
| フォーマット | `{job_name}/{year}/[{round}/]{sha256(url)[:16]}-{sanitized_filename}.pdf` |
| 決定性 | 同じ URL → 同じパス (再 run で重複アップロード回避) |
| filename サニタイズ | query string 除去、空白等は `-` に置換、`.pdf` 拡張子強制 |

### 7.3 `biyearly_admission_etl` への統合

| 観点 | 仕様 |
|---|---|
| 引数追加 | `archive: PdfArchive \| None = None` (default は `NullArchive`) |
| 処理順 | fetch → **archive.put** → Docling table 抽出 → parse → upsert (アーカイブが parse より先) |
| `AdmissionCrawlOutcome` 拡張 | `archive_path` / `archive_backend` を追加 (記録 / 監視用) |
| dry_run の挙動 | DB upsert は skip するが archive.put は実行 (出典担保) |

### 7.4 `EtlConfig` 拡張

| env | 用途 |
|---|---|
| `FUJISAWA_ETL_PDF_ARCHIVE_BACKEND` | `'gcs'` / `'local'` / `'null'` |
| `FUJISAWA_ETL_PDF_ARCHIVE_BUCKET` | gcs backend のバケット名 (default: `fujisawa-pdf-archive`) |
| `FUJISAWA_ETL_PDF_ARCHIVE_LOCAL_ROOT` | local backend のルート (default: `/tmp/fujisawa-pdf-archive`、本番は override 必須) |

`build_archive_from_config(backend, bucket, local_root)` factory で `PdfArchive` を組み立て可能。

### 7.5 Phase 4-2 後続 Job への引き継ぎ

monthly_vacancy / yearly_navi / wayback_backfill (4-2d / 4-2e / 4-2g) は **本 PR の `PdfArchive` を最初から DI に組み込む** こと:

```python
async def run_<job_name>(*, ..., archive: PdfArchive | None = None, ...):
    _archive = archive or NullArchive()
    # fetch → _archive.put → parse → upsert
```

これにより proposal §4.5 line 204 (GCS `fujisawa-raw` / `fujisawa-pdf-archive` への一次保存) の方針が一気通貫で守られる。

---

## 8. Phase 4-2c で確定した詳細

### 8.0 設計判断

- **PDF 表抽出を `pdf_pipeline` に追加 (`extract_tables`)**: 既存の `extract_chunks` (テキスト本文) と並列に、Docling が認識した表構造を `PdfTable` (HtmlTable と同形) で取り出す。lazy import で `[pdf]` extra なしでも import 可能。
- **`PdfTable` は `HtmlTable` と同形**: `headers: list[str]` / `rows: list[list[str]]` / `page_number: int | None`。後続 ETL Job が同じ parser 形式を流用できる (Phase 4-2d / 4-2g)。
- **`AdmissionRepo` の upsert は逐次実行**: 行ごとに `INSERT ... ON CONFLICT DO UPDATE` を発行。160 施設 × 6 age_class = 960 件規模で十分速く、batch insert より単純。
- **令和 4 年 min_index も対応**: `min_basic_score` / `min_priority` / `min_coordination_score` / `min_index_notation` は Phase 4-2g (`wayback_backfill`) で埋まる前提。`parse_min_index_notation("10F11※")` は本 PR で同梱 (共通 utility)。
- **`facility_id` 解決は `FacilityResolver` 経由**: ETL は `build_facility_resolver(FacilitiesRepo)` で `facilities` マスタから resolver を組み立て、PDF から拾った施設名を解決。**`NoMatchError` は parser が握り潰して該当行 skip** (誤った facility_id での upsert を防ぐ)。
- **`table_extractor` は DI 可能**: テストでは Docling を呼ばずに mock 表データを直接注入。実 Docling 統合は Phase 4-2h のデプロイ時に手動 smoke (proposal §4.6)。
- **PDF バイナリ取得の限界**: 現状 `PoliteFetcher.fetch().text` は str を返すため PDF 取得は latin-1 ラウンドトリップで bytes 化している。実機での PDF パス修正は Phase 4-2h で `fetch_bytes()` 拡張として対応予定。

### 8.1 `AdmissionRepo` (`etl/_repos/admission.py`)

| 観点 | 仕様 |
|---|---|
| PK | `(facility_id, year, round, age_class)` |
| `upsert_many(records)` | 行ごとに `INSERT ... ON CONFLICT DO UPDATE`。0 件は no-op |
| `count(year=?, round=?)` | フィルタ可能な COUNT (smoke / 監視用) |
| `round` validator | `'1st' | '2nd'` 以外は ValueError |
| `age_class` 範囲 | 0 〜 5 (Pydantic Field ge=0, le=5) |

実装: [`fujisawa_platform/etl/_repos/admission.py`](../fujisawa_platform/etl/_repos/admission.py)
テスト: 9 ケース PASS

### 8.2 `pdf_pipeline.extract_tables` + `PdfTable`

| 観点 | 仕様 |
|---|---|
| 関数 | `extract_tables(pdf_bytes) -> list[PdfTable]` |
| `PdfTable` | `headers` + `rows` + `page_number`。`HtmlTable` と同形 |
| 実装 | Docling lazy import → `document.tables` → 2D grid 抽出 |
| 未インストール時 | `DoclingNotInstalledError` (extract_chunks と同パターン) |

実装: [`fujisawa_platform/pdf_pipeline/pdf_table.py`](../fujisawa_platform/pdf_pipeline/pdf_table.py)
テスト: 3 ケース PASS (Docling インストール環境での integration は skip)

### 8.3 `admission_parser` (`etl/admission_parser.py`)

| 関数 | 用途 |
|---|---|
| `parse_admission_table(*, table, year, round, source_pdf_url, as_of, resolver)` | `PdfTable` → `list[AdmissionResultRecord]`。施設名列を「施設名 / 保育施設名 / 園名」から検出、年齢クラス列を regex (`(?P<age>[0-5])\s*歳児\s*(?P<kind>定員|申込|利用枠)`) で検出 |
| 施設名解決 | `resolver.resolve()` を呼び、`NoMatchError` は skip |
| 空 age_class | `定員 / 申込 / 利用枠` すべて空セルなら該当 age_class skip |
| `parse_min_index_notation("10F11※")` | `(basic, priority, coord)` 分解。`△` / `○` / `-` / `＼` / 空文字 / 不正フォーマットは None。Phase 4-2g 用 |

実装: [`fujisawa_platform/etl/admission_parser.py`](../fujisawa_platform/etl/admission_parser.py)
テスト: 18 ケース PASS

### 8.4 `build_facility_resolver` + `FacilitiesRepo.list_all`

| 観点 | 仕様 |
|---|---|
| `FacilitiesRepo.list_all() -> list[FacilityRecord]` | 全件 (~160) を `facility_id ORDER BY` で取得 |
| `build_facility_resolver(repo, *, threshold=0.85)` | `list_all` の結果を `ResolverEntry` に変換して `FacilityResolver` を組み立てる |
| aliases parse | `json.loads(str)` / list 直渡し / None の 3 ケースに対応 |

実装:
- [`fujisawa_platform/etl/_repos/facilities.py`](../fujisawa_platform/etl/_repos/facilities.py) (list_all 追加)
- [`fujisawa_platform/etl/facility_resolver_builder.py`](../fujisawa_platform/etl/facility_resolver_builder.py)

テスト: 5 ケース PASS

### 8.5 `biyearly_admission_etl` (`etl/biyearly_admission.py`)

| 観点 | 仕様 |
|---|---|
| 起動 | `run_biyearly_admission(*, pdf_url, year, round, fetcher_config, admission_repo, runs_repo, resolver, run_id, table_extractor=None, ...)` |
| 処理 | PoliteFetcher PDF fetch → Docling 表抽出 → `parse_admission_table` → `upsert_many` |
| `table_extractor` DI | 実 Docling を回避してテストできる |
| dry-run | parse は行うが `repo.upsert_many` を呼ばない |
| source_hash | PDF bytes の SHA-256 |
| 個別 fetch 失敗 | `httpx.HTTPStatusError` を上位に伝搬 → `run_etl_job` ラッパー側で `failed` 扱い |

実装: [`fujisawa_platform/etl/biyearly_admission.py`](../fujisawa_platform/etl/biyearly_admission.py)
テスト: 7 ケース PASS

---

## 9. Phase 4-2b で確定した詳細

### 9.0 設計判断

- **`facilities` は UPSERT + 条件付き DELETE を 1 トランザクション**: proposal 0003 §4.5.5 の方針 (2026-05-18 改訂)。 旧設計の「全削除 → 全 INSERT」は admission_results 等が FK 参照を持つようになると `ForeignKeyViolationError` で fail するため、 `INSERT ... ON CONFLICT DO UPDATE` で incoming を UPSERT し、 incoming に無く下流 4 テーブル (`admission_results` / `vacancy_snapshots` / `application_snapshots` / `competition_stats`) から参照も無い orphan のみ DELETE する設計に変更。 atomicity は単一トランザクションで維持。 consumer 側は SELECT 失敗時に tenacity retry で吸収する想定。
- **facility_id は `<type-slug>-<sha256[:12]>`**: 名前ベースの決定的 ID。半年ごとに UPSERT しても同じ施設には同じ ID が返るので、`vacancy_snapshots.facility_id REFERENCES facilities` の FK が壊れない。例: `kouritsu-3a4b5c6d7e8f` (公立保育所 / 藤沢保育園)。 この stable ID 設計があるため UPSERT が成立する (DELETE → INSERT は不要)。
- **HTML テーブル抽出は BeautifulSoup 単独で完結**: 調査ノート §A4-3 では `pandas.read_html` + BS4 の 2 段だったが、リンク URL を別途 BS4 で取り直すなら最初から BS4 で `<th>` / `<td>` を見れば十分。pandas 依存を避け、`_html_table.py` 1 ファイルで完結させた。
- **認可テーブル 5 種は HTML 内の出現順で type を割当**: `_AUTHORIZED_TABLE_TYPES = ["公立保育所", "法人等保育所", "認定こども園", "小規模保育事業", "家庭的保育事業"]`。HTML 構造が変わってテーブルが減った場合は `zip(strict=False)` で parsable な範囲だけ処理する fallback。
- **認可外の facility_type は施設名末尾の括弧から抽出**: 「A 保育園 (藤沢型 A 型)」→ name="A 保育園", facility_type="藤沢型 A 型"。括弧無しは "認可外保育施設" にフォールバック。
- **アクセス情報の駅 + 徒歩分数は所在地カラムから regex 抽出**: 「藤沢駅北口徒歩 7 分」のような表記を `_WALK_MINUTES` で parse。マッチしないなら `(None, None)` で通常の住所扱い。

### 9.1 `FacilitiesRepo` (`etl/_repos/facilities.py`)

| メソッド | 仕様 |
|---|---|
| `replace_all(records)` | `async with conn.transaction(): INSERT ... ON CONFLICT (facility_id) DO UPDATE × N → DELETE WHERE facility_id != ALL($1) AND NOT EXISTS (下流 4 テーブルへの参照)`。空 list でも条件付き DELETE は走る (orphan 陳腐化対応) |
| `count()` | `SELECT COUNT(*) FROM facilities` (smoke / 監視用) |
| 引数 jsonb | `aliases` は `json.dumps(..., ensure_ascii=False)` で `$10::jsonb` バインド (asyncpg は文字列を json型に渡せる) |

実装: [`fujisawa_platform/etl/_repos/facilities.py`](../fujisawa_platform/etl/_repos/facilities.py)
テスト: 7 ケース PASS

### 9.2 HTML テーブル抽出 (`etl/_html_table.py`)

| 観点 | 仕様 |
|---|---|
| 関数 | `extract_tables_with_links(html) -> list[HtmlTable]` |
| `HtmlTable` | `headers: list[str]` / `rows: list[list[str]]` / `row_links: list[dict[int, str]]` |
| ヘッダ検出 | `<thead>` 優先 → 1 行目が全て `<th>` ならそれを headers → なければ空 list |
| リンク抽出 | 各セル内の最初の `<a href>` を `row_links[行 idx][列 idx]` に格納 |
| セルテキスト | `get_text(strip=True)` で前後空白除去 |

実装: [`fujisawa_platform/etl/_html_table.py`](../fujisawa_platform/etl/_html_table.py)
テスト: 8 ケース PASS

### 9.3 facility_parser (`etl/facility_parser.py`)

| 関数 | 用途 |
|---|---|
| `slugify_facility_id(facility_type, name)` | `<type-slug>-<sha256[:12]>` の決定的 ID 生成 |
| `parse_walk_minutes(text)` | 「藤沢駅北口徒歩 7 分」→ ("藤沢駅", 7)。マッチなしは (None, None) |
| `parse_authorized_table(*, table, facility_type, source_url, as_of)` | 認可施設テーブル (3 列以上) → `list[FacilityRecord]`。4 列目以降のリンクを `official_url` に採用 |
| `parse_unauthorized_table(*, table, source_url, as_of)` | 認可外 (4 列以上) → `list[FacilityRecord]`。括弧内類型 + 駅徒歩分数 + 定員を parse |

実装: [`fujisawa_platform/etl/facility_parser.py`](../fujisawa_platform/etl/facility_parser.py)
テスト: 17 ケース PASS

### 9.4 `half_yearly_facility_etl` (`etl/half_yearly_facility.py`)

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

## 10. Phase 4-2a で確定した詳細

### 10.0 設計判断

- **ETL 共通フレームを最初に整備**: `etl/_runner.py` (実行ラッパー) / `etl/_repos/etl_runs.py` (`etl_runs` テーブル) / `etl/_html.py` (本文抽出) / `etl/config.py` (env) の 4 つを 4-2a で同梱。これ以降の Job (4-2b〜g) はすべて `run_etl_job()` で包む。
- **`run_etl_job()` の 3 つの責務** (proposal 0003 §4.5.6):
  - **記録**: `etl_runs` に `started_at` で INSERT (`status='running'`) → 終了時に UPDATE (`status='success'|'failed'|'skipped_unchanged'`)
  - **fail-fast**: 直近 5 件すべて failed なら fn を呼ばずに `status='failed'` で記録 (再開は手動)
  - **source_hash skip**: `probe()` で計算した hash が前回 success と一致なら fn を呼ばずに `status='skipped_unchanged'`
- **個別 URL の例外は continue**: `weekly_crawl_etl` は 1,100+ URL を順に叩くため、1 URL の 4xx/5xx で全体を fail させない。`failed_urls` カウンタで追跡し、Job 全体は `success` で完了する (個別失敗は別途監視で検知)。
- **dry-run mode**: 各 Job は `dry_run=True` で **DB 書き込み無し / parse は行う** モードを持つ。Cloud Run Job デプロイ前の手動 smoke 用 (proposal 0003 §4.6 Manual / E2E)。
- **`_StoreLike` Protocol で DI**: `crawl_and_index` は `upsert_page` だけを持つ Protocol を要求するので、`PgvectorStore` (本番) / `InMemoryStore` (smoke) / `_RecordingStore` (テスト) が等しく差し込める。

### 10.1 `run_etl_job` ラッパー (`etl/_runner.py`)

| 観点 | 仕様 |
|---|---|
| 入力 | `job_name` / `run_id` / `repo: EtlRunsRepo` / `fn: () -> EtlRunResult` / 任意 `probe` / 任意 `now` |
| fail-fast | `repo.recent_runs(limit=5)` の全件 `failed` なら fn 呼ばず即時 failed |
| skip-unchanged | `probe()` の戻り値が `recent_runs` 中の最新 success の `source_hash` と一致なら `skipped_unchanged` |
| 例外捕捉 | fn 内例外は `<ClassName>: <message>` 形式で `error_message` に詰めて failed 扱い |
| 戻り値 | `EtlRunResult` (`rows_written` / `source_hash` / `source_url` / `status` / `error_message`) |

実装: [`fujisawa_platform/etl/_runner.py`](../fujisawa_platform/etl/_runner.py)
テスト: 8 ケース PASS

### 10.2 `EtlRunsRepo` (`etl/_repos/etl_runs.py`)

| メソッド | 仕様 |
|---|---|
| `start_run(*, job_name, run_id, started_at, source_url=None)` | `INSERT INTO etl_runs (..., status='running')` |
| `finish_run(*, job_name, run_id, finished_at, status, source_hash=None, rows_written=None, error_message=None)` | `UPDATE etl_runs SET status, finished_at, source_hash, rows_written, error_message WHERE job_name AND run_id` |
| `recent_runs(job_name, *, limit=5)` | `ORDER BY started_at DESC LIMIT $2`、5 連敗 fail-fast 判定で利用 |

実装: [`fujisawa_platform/etl/_repos/etl_runs.py`](../fujisawa_platform/etl/_repos/etl_runs.py)
テスト: 6 ケース PASS

### 10.3 HTML 本文抽出 (`etl/_html.py`)

| 観点 | 仕様 |
|---|---|
| `extract_main_text(html)` | 優先順位: `<main>` → `<article>` → `<body>`。`<script>` / `<style>` / `<nav>` / `<footer>` / `<header>` / `<aside>` を decompose で除去 |
| `extract_title(html)` | `<title>` → `<h1>` の順で取得。Unicode (令和6年 等) は intact |
| 連続空白 | 1 つに正規化 (改行は保つ) |

実装: [`fujisawa_platform/etl/_html.py`](../fujisawa_platform/etl/_html.py)
テスト: 12 ケース PASS

### 10.4 `EtlConfig` (`etl/config.py`)

| グループ | env 変数 |
|---|---|
| DB | `FUJISAWA_ETL_DB_HOST` / `_PORT` (5432) / `_USER` / `_PASSWORD` / `_NAME` (`fujisawa_kb_db`) / `_POOL_MIN` / `_POOL_MAX` |
| HTTP | `FUJISAWA_ETL_USER_AGENT` (連絡先 URL 必須) / `_MIN_INTERVAL_SEC` (3.0) |
| Embedding | `FUJISAWA_ETL_VERTEX_PROJECT_ID` (None なら Mock) / `_VERTEX_LOCATION` / `_EMBEDDING_MODEL` / `_EMBEDDING_DIM` |
| Job 個別 | `FUJISAWA_ETL_<JOB>_ENABLED` (例: `WEEKLY_CRAWL_ENABLED`) — Phase 0 で段階導入 |

実装: [`fujisawa_platform/etl/config.py`](../fujisawa_platform/etl/config.py)
テスト: 4 ケース PASS

### 10.5 `weekly_crawl_etl` (`etl/weekly_crawl.py`)

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

### 10.6 Phase 4-2 後続 Job への引き継ぎ

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

## 11. Phase 4-1 で確定した詳細

### 11.0 設計判断

- **PgvectorStore は `asyncpg.Pool` を外部から受け取る**: クラス内で pool を作らず、consumer 側 (ETL Job / agent main) のライフサイクルでクローズする。短命接続を避けて Cloud SQL の同時接続上限を保護。driving-license-bot の `PgvectorQuestionBank` と同パターン。
- **`pgvector.asyncpg.register_vector` は 1 クエリごとに呼ぶ**: Pool から acquire される接続は再利用されるが、再利用時の register は no-op になる前提で愚直に呼ぶ (driving-license-bot と同方針)。
- **cosine 距離は `<=>` 演算子、類似度は `1 - (<=>)`**: pgvector 標準。HNSW より ivfflat (`lists=100`) を schema で採用済 (proposal §4.3)。
- **asyncpg / pgvector は lazy import**: `[pgvector]` extra なしでも fujisawa-platform を import できるようにする (consumer が in-memory のみ使うケースを許容)。
- **pgvector 単体テストは asyncpg を mock**: 実 Cloud SQL は CI に持たない。proposal §4.6 の通り、接続 smoke は Phase 4-2 ETL デプロイ時に手動。

### 11.1 PgvectorStore の挙動

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

### 11.2 build_pgvector_pool helper

| 観点 | 仕様 |
|---|---|
| 引数 | `host` / `port=5432` / `user` / `password` / `database` / `min_size=1` / `max_size=5` |
| 戻り値 | `asyncpg.Pool` |
| Cloud SQL Auth Proxy | `host="127.0.0.1"` を渡すだけで対応可能 |
| ライフサイクル | 呼出側が `await pool.close()` する (本ライブラリは管理しない) |

実装: 同上 (`pgvector_store.py` 末尾)

### 11.3 Phase 4-2 への引き継ぎ

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

## 12. Phase 3 で確定した詳細

### 12.0 設計判断

- **緊急情報 RSS の 5 分 poll loop は LINE bot 側に置く**: 共通基盤側は `parse_feed(bytes) -> list[RssEntry]` の純粋な parse helper のみ提供する (proposal 0003 §4.5.4 の方針: 「5 分間隔の job が他 consumer にも見えると混乱する」)。LINE bot 側 `fujisawa-info-bot/batch/poll_rss.py` が `seen_guids` セットを Firestore で管理する。
- **`parse_feed` は RSS 2.0 / Atom 両対応**: 藤沢市 HP がどちらを返すか実機未確認のため、両 schema を 1 関数で吸収。`<rss>` / `<feed>` のルート要素で分岐。
- **Wayback クライアントは `PoliteFetcher` を流用しない**: web.archive.org は別ホストで polite ルール (5 秒間隔 / 503 retry) も別。共通化するメリットより独立 client の方が単純。
- **CDX クエリは statuscode != 200 を捨てる**: Wayback には 404 / 301 のスナップショットも履歴として残るが、PDF 取得は不可能のため `_rows_to_snapshots` で除外。
- **Wayback バックフィルは Phase 4 で 1 度きり実行**: 本 PR ではクライアント実装のみ。実データ投入は Phase 4 の `etl/wayback_backfill.py` で `admission_results` (令和 4-6 年) + `competition_stats.historical_minimum_index_2022` に流し込む。

### 12.1 緊急情報 RSS parser (`crawler/rss_poller.py`)

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

### 12.2 Wayback クライアント (`crawler/wayback.py`)

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

### 12.3 Phase 4-2 への引き継ぎ事項

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

## 13. Phase 2 で確定した詳細

### 13.0 設計判断

- **PgvectorStore (本番 asyncpg 実装) は Phase 4 に延期**: Cloud SQL への接続ライフサイクルが ETL Cloud Run Jobs と一体のため、Phase 4 で同時に実装。Phase 2 範囲では Protocol + InMemoryStore (Mock) を提供。
- **Embedding は Protocol + Mock + Vertex の 3 段構成**: driving-license-bot の `app/agent/embedding.py` パターンを踏襲。Vertex は lazy import (`uv sync --extra vertex` で導入)。
- **Docling は完全 lazy import**: `[pdf]` extra として ML deps を分離。Phase 4 ETL でのみ必要。
- **rapidfuzz scorer は `fuzz.ratio` (Levenshtein)**: 日本語は token boundaries が無いため、token-set ratio より文字レベル ratio が中黒 (なかぐろ「・」、例: 「キディ鵠沼・藤沢」⇔「キディ鵠沼藤沢」) / typo に強い。

### 13.1 FacilityResolver の挙動

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

### 13.2 EmbeddingClient の Protocol

| 観点 | 仕様 |
|---|---|
| Protocol | `dimension` プロパティ + `embed(text) -> list[float]` + `embed_batch(texts)` |
| MockEmbeddingClient | SHA-256 ハッシュベースで決定的、L2 正規化済 (cosine = 内積) |
| VertexEmbeddingClient | `text-embedding-004` (768 dim)、認証は Workload Identity、import は lazy |
| 次元 | default 768 (Vertex `text-embedding-004` に合わせる) |

実装: [`fujisawa_platform/knowledge_base/embedding.py`](../fujisawa_platform/knowledge_base/embedding.py)
テスト: 10 ケース PASS

### 13.3 KnowledgeStore (pages テーブル抽象)

| 観点 | 仕様 |
|---|---|
| Protocol | `upsert_page` / `get_page` / `delete_page` / `search_pages` (全部 async) |
| InMemoryStore | dict ベース、cosine = 内積で full scan top-k |
| 検索フィルタ | `category` で絞り込み (将来 region / age_class 等を追加) |
| dimension 検証 | upsert / search 時に embedding 次元が store の `embedding_dim` と一致するか確認 |
| 本番 PgvectorStore | Phase 4 で追加 (本 PR は雛形のみ) |

実装: [`fujisawa_platform/knowledge_base/store.py`](../fujisawa_platform/knowledge_base/store.py)
テスト: 11 ケース PASS

### 13.4 pdf_pipeline の 3 helpers

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

## 14. Phase 1 で確定した詳細

### 14.1 PoliteFetcher の挙動

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

### 14.2 sitemap.xml の parse 仕様

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

### 14.3 Skill File 5 種

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

### 14.4 pgvector schema (8 テーブル)

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

## 15. NFR (proposal 0003 §3 から要約)

| 観点 | 目標 / 制約 |
|---|---|
| 性能 | crawler 1 URL/3s、sitemap 全クロール 1 時間 / pgvector top-10 < 200ms p95 |
| コスト | Cloud SQL instance 共有で月 ¥0 増、Vertex Embedding 月 ¥10 以下 |
| プライバシー | public 情報のみ扱う、PII は consumer 側 |
| 可用性 | sitemap 取得失敗時は旧データ温存 |
| 保守性 | カバレッジ目標 80%、Phase 1 の crawler / skills / db は 90%+ 達成済 |

詳細は proposal 0003 §3 / §5.4 参照。

---

## 16. 関連ドキュメント

- [`../README.md`](../README.md) — Quickstart / 利用方法
- proposal 0003-0005 (上記 §1)
- 事前調査ノート (上記 §1)
- [`fujisawa_platform/skills/`](../fujisawa_platform/skills/) — 共通 SKILL.md 5 種
- [`fujisawa_platform/db/init_schema.sql`](../fujisawa_platform/db/init_schema.sql) — pgvector schema

---

## 17. 用語集

| 用語 | 意味 |
|---|---|
| polite fetcher | UA 明示 + interval + IfMS を強制する礼儀正しい HTTP 取得層 |
| Wayback バックフィル | Internet Archive 経由で過去 PDF を取得する手法 |
| 鮮度メタデータ | `as_of` / `source_url` / `snapshot_date` を含む共通型 (`FreshnessMetadata`) |
| consumer (本基盤の) | path dep で本ライブラリを使う 2 エージェント (info-bot / 保活) |
| etl_role / consumer_role | DB の IAM ロール分離 (proposal 0003 §4.5.3) |
| `historical_minimum_index_2022` | 令和 4 年の最低内定指数。proposal 0005 のハイブリッドモデル用 (M8) |
