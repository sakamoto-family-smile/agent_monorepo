"""Alembic environment. 同期接続で sync_engine を生成する。"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# app をパスに追加
_APP_DIR = Path(__file__).resolve().parents[2] / "app"
sys.path.insert(0, str(_APP_DIR))

from models.db import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# 環境変数 DB_URL が設定されていれば alembic.ini を上書き
_env_db = os.environ.get("DB_URL", "").strip()
if _env_db:
    # async ドライバが指定されていれば同期版へ差し替え
    sync_url = (
        _env_db
        .replace("sqlite+aiosqlite:", "sqlite:")
        .replace("postgresql+asyncpg:", "postgresql+psycopg:")
    )
    config.set_main_option("sqlalchemy.url", sync_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
