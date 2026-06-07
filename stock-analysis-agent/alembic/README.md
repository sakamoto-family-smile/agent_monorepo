# Alembic migrations (stock-analysis-agent / PROPOSAL-0011 P2-B)

core 4 テーブル（`ticker_dictionary` / `price_cache` / `reports` / `alerts`）の
スキーマを管理する。`edinet_documents` は EDINET 有効化（P3）まで対象外
（aiosqlite の `edinet_index_repo` 側で自己管理）。

## URL 解決

`alembic/env.py` が `config.settings.resolved_database_url` を再利用する:

```
DATABASE_URL > DB_HOST+DB_USER+DB_NAME(+DB_PASSWORD) 組立 > DB_PATH(sqlite)
```

## 使い方

```bash
# 最新まで適用 (dev: sqlite)
DATABASE_URL="sqlite+aiosqlite:///./data/stock_analysis.db" uv run alembic upgrade head

# prod (Cloud Run): コンテナ起動時に DB_HOST/DB_USER/DB_NAME/DB_PASSWORD から組立てて適用
uv run alembic upgrade head

# 新しい migration を追加
uv run alembic revision -m "add xxx"
```

## dev/test と prod の使い分け

- dev/test: `DB_AUTO_CREATE=true`（既定）で `init_db()` が `create_all` + seed する
  ため、alembic は必須ではない（スキーマ進化の記録用）。
- prod Postgres: `DB_AUTO_CREATE=false` にして **alembic がスキーマの単一の真実**。
  コンテナ起動時に `alembic upgrade head` を実行してから uvicorn を起動する
  （Dockerfile の起動コマンド参照）。`init_db()` は seed のみ行う。
