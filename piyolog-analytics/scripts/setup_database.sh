#!/usr/bin/env bash
# Phase 1 残 TODO: SQLite スキーマを手動で初期化するスクリプト。
#
# 既定の挙動:
# - DATABASE_URL が SQLite (sqlite+aiosqlite:///...) を指していれば metadata.create_all を流す
# - Postgres を指していたら警告して exit 1 (本番は alembic upgrade head を使う)
#
# 通常運用では `app/main.py` の lifespan が `db_auto_create=true` のとき自動初期化するが、
# ops 用途で意図的に手動実行したい場合 (Cloud Run 起動前のセットアップ等) のために提供する。
#
# 使い方:
#   cd piyolog-analytics
#   uv run python scripts/setup_database.sh
#   # or:
#   DATABASE_URL=sqlite+aiosqlite:///./data/piyolog.db ./scripts/setup_database.sh

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f pyproject.toml ]]; then
    echo "[setup_database] piyolog-analytics ディレクトリで実行してください" >&2
    exit 2
fi

# uv 経由で Python コードを直に実行
exec uv run python -c '
import asyncio
import os
import sys
sys.path.insert(0, "app")

from config import settings
from repositories.event_repo import EventRepo


async def main() -> int:
    url = settings.resolved_database_url
    print(f"[setup_database] target: {url}")
    if "sqlite" not in url:
        print(
            "[setup_database] ERROR: This script is intended for SQLite only.\n"
            "                For Postgres, use `alembic upgrade head` instead.",
            file=sys.stderr,
        )
        return 1
    repo = EventRepo(database_url=url)
    try:
        await repo.initialize()
        count = await repo.count_events(family_id=settings.family_id)
        print(f"[setup_database] schema created (rows={count})")
        return 0
    finally:
        await repo.dispose()


sys.exit(asyncio.run(main()))
'
