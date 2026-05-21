-- fujisawa_kb_db schema (proposal 0003 §4.3)
--
-- driving-license-bot 既存 Cloud SQL instance に DB を追加する想定。
-- 適用前提:
--   1. CREATE DATABASE fujisawa_kb_db; (Cloud SQL コンソール or gcloud)
--   2. psql -d fujisawa_kb_db -f init_schema.sql
--
-- IAM ロール (proposal 0003 §4.5.3):
--   - consumer_role: SELECT のみ (info-bot / 保活 が使用)
--   - etl_role:      INSERT/UPSERT/DELETE (ETL Cloud Run Jobs が使用)

CREATE EXTENSION IF NOT EXISTS vector;

-- ─────────────────────────────────────────────────────────────────────
-- pages: sitemap.xml クロール結果 (LINE bot RAG 用)
-- weekly_crawl_etl が書き込む
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pages (
    page_id        TEXT PRIMARY KEY,                  -- url の SHA-256 hash
    url            TEXT NOT NULL,
    title          TEXT,
    content        TEXT NOT NULL,
    embedding      vector(768) NOT NULL,
    category       TEXT,                              -- 防災 / 子育て / ゴミ / etc.
    fetched_at     TIMESTAMPTZ NOT NULL,
    last_modified  TIMESTAMPTZ,                       -- HTTP Last-Modified
    schema_version TEXT NOT NULL DEFAULT 'v1'
);

CREATE INDEX IF NOT EXISTS pages_embedding_ivfflat
    ON pages USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS pages_category_idx ON pages (category);
CREATE INDEX IF NOT EXISTS pages_fetched_at_idx ON pages (fetched_at);

-- ─────────────────────────────────────────────────────────────────────
-- pdf_documents: 申込ナビ等の PDF を Docling で chunk 化したもの
-- yearly_navi_etl が書き込む
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pdf_documents (
    pdf_id         TEXT NOT NULL,                     -- url の SHA-256 hash
    chunk_index    INTEGER NOT NULL,                  -- Docling chunk 単位
    url            TEXT NOT NULL,
    chunk_text     TEXT NOT NULL,
    embedding      vector(768) NOT NULL,
    page_number    INTEGER,                           -- 元 PDF のページ番号
    fetched_at     TIMESTAMPTZ NOT NULL,
    pdf_hash       TEXT NOT NULL,                     -- PDF 全体の SHA-256
    schema_version TEXT NOT NULL DEFAULT 'v1',
    PRIMARY KEY (pdf_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS pdf_documents_embedding_ivfflat
    ON pdf_documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS pdf_documents_pdf_hash_idx ON pdf_documents (pdf_hash);

-- ─────────────────────────────────────────────────────────────────────
-- facilities: 認可 / 認可外保育施設マスタ (160 件)
-- half_yearly_facility_etl が書き込む。保活 SearchAgent が読む。
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS facilities (
    facility_id        TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    facility_type      TEXT NOT NULL,                 -- 公立保育所 / 法人等保育所 / 認定こども園 / etc.
    address            TEXT NOT NULL,
    phone              TEXT,
    capacity           INTEGER,
    nearest_station    TEXT,
    walk_minutes       INTEGER,
    official_url       TEXT,
    aliases            JSONB NOT NULL DEFAULT '[]',   -- 表記ゆれ吸収用
    -- 緯度経度 (将来 PostGIS 対応するなら point に。Phase 1 は単純カラム)
    lat                DOUBLE PRECISION,
    lng                DOUBLE PRECISION,
    -- 鮮度メタデータ (FreshnessMetadata に対応)
    source_url         TEXT NOT NULL,
    as_of              TIMESTAMPTZ NOT NULL,
    schema_version     TEXT NOT NULL DEFAULT 'v1'
);

CREATE INDEX IF NOT EXISTS facilities_facility_type_idx ON facilities (facility_type);
CREATE INDEX IF NOT EXISTS facilities_nearest_station_idx ON facilities (nearest_station);

-- ─────────────────────────────────────────────────────────────────────
-- vacancy_snapshots: 月次空き状況スナップショット
-- monthly_vacancy_etl が書き込む。保活 VacancyAgent が読む。
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vacancy_snapshots (
    facility_id    TEXT NOT NULL REFERENCES facilities(facility_id),
    year_month     TEXT NOT NULL,                     -- 'YYYY-MM' 形式
    age_class      INTEGER NOT NULL,                  -- 0..5
    vacancies      INTEGER NOT NULL DEFAULT 0,
    snapshot_date  DATE NOT NULL,                     -- PDF 掲載日
    source_pdf_url TEXT NOT NULL,
    fetched_at     TIMESTAMPTZ NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'v1',
    PRIMARY KEY (facility_id, year_month, age_class)
);

CREATE INDEX IF NOT EXISTS vacancy_snapshots_year_month_idx ON vacancy_snapshots (year_month);

-- ─────────────────────────────────────────────────────────────────────
-- application_snapshots: 月次申込状況スナップショット
-- monthly_vacancy_etl が同 Job で書き込む。
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS application_snapshots (
    facility_id    TEXT NOT NULL REFERENCES facilities(facility_id),
    year_month     TEXT NOT NULL,
    age_class      INTEGER NOT NULL,
    applicants     INTEGER NOT NULL DEFAULT 0,
    capacity       INTEGER NOT NULL,
    snapshot_date  DATE NOT NULL,
    source_pdf_url TEXT NOT NULL,
    fetched_at     TIMESTAMPTZ NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'v1',
    PRIMARY KEY (facility_id, year_month, age_class)
);

CREATE INDEX IF NOT EXISTS application_snapshots_year_month_idx ON application_snapshots (year_month);

-- ─────────────────────────────────────────────────────────────────────
-- admission_results: 4月入所結果 (年 2 回 + Wayback バックフィル)
-- biyearly_admission_etl + wayback_backfill が書き込む。
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admission_results (
    facility_id              TEXT NOT NULL REFERENCES facilities(facility_id),
    year                     INTEGER NOT NULL,        -- 2022, 2023, ...
    round                    TEXT NOT NULL,           -- '1st' | '2nd'
    age_class                INTEGER NOT NULL,
    applicants_at_deadline   INTEGER,
    capacity                 INTEGER,
    vacancy_after            INTEGER,
    -- 令和 4 年のみ存在: 最低内定指数 (proposal 0005 §4.4 / 調査 §A2-2)
    min_basic_score          INTEGER,
    min_priority             TEXT,                    -- 'A'..'K' (H なし)
    min_coordination_score   INTEGER,
    min_index_notation       TEXT,                    -- '10F11※' 形式
    source_pdf_url           TEXT NOT NULL,
    as_of                    TIMESTAMPTZ NOT NULL,
    schema_version           TEXT NOT NULL DEFAULT 'v1',
    PRIMARY KEY (facility_id, year, round, age_class)
);

CREATE INDEX IF NOT EXISTS admission_results_year_idx ON admission_results (year);

-- ─────────────────────────────────────────────────────────────────────
-- competition_stats: 過去倍率の集計結果 (3 段階分類 + 令和 4 正確値)
-- monthly_stats_compute が書き込む (外部 fetch なし、上記から算出)
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS competition_stats (
    facility_id                          TEXT NOT NULL REFERENCES facilities(facility_id),
    age_class                            INTEGER NOT NULL,
    history                              JSONB NOT NULL DEFAULT '[]',   -- [{year, ratio, vacancy_after_1st, level}, ...]
    avg_ratio_3y                         DOUBLE PRECISION,
    competition_level                    TEXT,                          -- '超人気' | '人気' | '比較的入りやすい' | 'data_unavailable'
    trend                                TEXT,                          -- 'rising' | 'stable' | 'declining'
    confidence                           TEXT NOT NULL,                 -- 'high' | 'medium' | 'low' | 'unknown'
    historical_minimum_index_2022        JSONB,                         -- {basic, priority, coord, notation, source_pdf_url}
    based_on                             JSONB NOT NULL DEFAULT '[]',
    last_updated                         TIMESTAMPTZ NOT NULL,
    schema_version                       TEXT NOT NULL DEFAULT 'v1',
    PRIMARY KEY (facility_id, age_class)
);

CREATE INDEX IF NOT EXISTS competition_stats_level_idx ON competition_stats (competition_level);

-- ─────────────────────────────────────────────────────────────────────
-- etl_runs: ETL ジョブ実行履歴 (差分検知用ハッシュ + 失敗追跡)
-- 各 Job が必ず追記する。
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS etl_runs (
    job_name        TEXT NOT NULL,
    run_id          TEXT NOT NULL,                    -- '<job_name>-<YYYYMMDD>-<HHMM>'
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL,                    -- 'running' | 'success' | 'failed' | 'skipped_unchanged' | 'aborted'
    source_url      TEXT,
    source_hash     TEXT,                             -- 取得元のSHA-256 (前回と同じならスキップ)
    rows_written    INTEGER,
    error_message   TEXT,
    PRIMARY KEY (job_name, run_id)
);

CREATE INDEX IF NOT EXISTS etl_runs_started_at_idx ON etl_runs (started_at DESC);
