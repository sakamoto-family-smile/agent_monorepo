"""
非同期 SQLAlchemy エンジン・セッションの一元管理。

テストでは `db_url` を上書きして init_engine() を呼び直すことで差し替える。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings
from models.db import Base

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _prepare_sqlite_dir(url: str) -> None:
    """SQLite URL の場合、親ディレクトリを作成する。"""
    marker = "sqlite+aiosqlite:///"
    if not url.startswith(marker):
        return
    path = url.removeprefix(marker)
    if path == ":memory:":
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def init_engine(db_url: str | None = None) -> AsyncEngine:
    """エンジンとセッションファクトリを初期化する。"""
    global _engine, _session_factory
    url = db_url or settings.db_url
    _prepare_sqlite_dir(url)
    _engine = create_async_engine(url, future=True, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    logger.info("DB engine initialized: %s", url.split("@")[-1])  # 認証情報を出さない
    return _engine


async def init_db() -> None:
    """
    開発・テスト用: SQLAlchemy メタデータからテーブルを作る。
    本番 (Postgres) では Alembic migration を使うこと。
    """
    if _engine is None:
        init_engine()
    assert _engine is not None
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """with 句ベースの使い捨てセッション。"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session_dep() -> AsyncIterator[AsyncSession]:
    """FastAPI Depends 用。トランザクションはルート側で管理する想定。"""
    factory = get_session_factory()
    async with factory() as session:
        yield session
