"""Alembic 環境設定。SQLAlchemy 2.0 async + 同期実行 (online)。"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# alembic.ini で `prepend_sys_path = .:app` してあるが、
# direct invocation でも import が通るようパスを明示挿入する。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
for p in (str(PROJECT_ROOT), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from repositories.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_url() -> str:
    """env から SQLAlchemy URL を解決する。

    優先度: `DATABASE_URL` > `PIYOLOG_DB_PATH` (sqlite) > alembic.ini の `sqlalchemy.url`。
    """
    if (url := os.getenv("DATABASE_URL")):
        return url
    if (path := os.getenv("PIYOLOG_DB_PATH")):
        return f"sqlite+aiosqlite:///{path}"
    return config.get_main_option("sqlalchemy.url") or ""


def _assert_url(url: str) -> str:
    if not url:
        raise RuntimeError(
            "DATABASE_URL or PIYOLOG_DB_PATH must be set for Alembic migrations."
        )
    return url


def run_migrations_offline() -> None:
    url = _assert_url(_resolve_url())
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    url = _assert_url(_resolve_url())
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = url
    connectable = async_engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_migrations_online_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
