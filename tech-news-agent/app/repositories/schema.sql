-- tech-news-agent hot-path state (small SQLite)
-- 分析対象の記事本体は analytics-platform の JSONL に emit し、dbt → DuckDB で
-- 集計する。SQLite には「重複配信を避けるための配信済み履歴」だけを持たせる。

CREATE TABLE IF NOT EXISTS delivered_articles (
  article_id TEXT PRIMARY KEY,
  title TEXT,
  source_name TEXT,
  source_type TEXT,
  url_normalized TEXT,
  delivered_at TEXT NOT NULL,       -- ISO8601 (UTC)
  digest_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_delivered_at
  ON delivered_articles(delivered_at);

CREATE TABLE IF NOT EXISTS digests (
  digest_id TEXT PRIMARY KEY,
  generated_at TEXT NOT NULL,
  delivered_at TEXT,
  status TEXT NOT NULL,             -- 'pending' | 'sent' | 'failed'
  article_count INTEGER NOT NULL DEFAULT 0,
  line_status_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_digests_generated_at
  ON digests(generated_at);
