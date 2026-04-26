# Alembic migrations

```bash
# 現在の DB を最新に上げる
make migrate                     # = uv run alembic upgrade head

# 1 つ戻す
uv run alembic downgrade -1

# 新規 migration (model 変更後)
uv run alembic revision --autogenerate -m "add ..."
```

`DATABASE_URL` か `PIYOLOG_DB_PATH` のどちらかが必須。
`alembic/env.py` で env から読み取り、`sqlalchemy.url` を上書きする。

dev/test (SQLite) は `EventRepo.initialize()` の `create_all` で代替できるため、
Alembic は **本番 (Postgres)** で主に使う想定。
