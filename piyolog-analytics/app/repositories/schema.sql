-- piyolog-analytics SQLite schema (Phase 1)

CREATE TABLE IF NOT EXISTS piyolog_events (
  event_id TEXT PRIMARY KEY,
  family_id TEXT NOT NULL,
  source_user_id TEXT NOT NULL,
  child_id TEXT NOT NULL DEFAULT 'default',
  event_timestamp TEXT NOT NULL,        -- ISO8601 with offset (+09:00)
  event_date TEXT NOT NULL,             -- YYYY-MM-DD (JST)
  event_type TEXT NOT NULL,
  volume_ml REAL,
  left_minutes INTEGER,
  right_minutes INTEGER,
  sleep_minutes INTEGER,
  temperature_c REAL,
  weight_kg REAL,
  height_cm REAL,
  head_circumference_cm REAL,
  memo TEXT,
  raw_text TEXT,
  import_batch_id TEXT NOT NULL,
  imported_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_family_date
  ON piyolog_events(family_id, event_date);

CREATE INDEX IF NOT EXISTS idx_events_family_type_date
  ON piyolog_events(family_id, event_type, event_date);

CREATE INDEX IF NOT EXISTS idx_events_batch
  ON piyolog_events(import_batch_id);

CREATE TABLE IF NOT EXISTS import_batches (
  batch_id TEXT PRIMARY KEY,
  family_id TEXT NOT NULL,
  source_user_id TEXT NOT NULL,
  source_filename TEXT,
  raw_text_hash TEXT NOT NULL,
  event_count INTEGER NOT NULL DEFAULT 0,
  imported_at TEXT NOT NULL,
  rolled_back_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_batches_family
  ON import_batches(family_id, imported_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_batches_hash_dedup
  ON import_batches(family_id, raw_text_hash) WHERE rolled_back_at IS NULL;
