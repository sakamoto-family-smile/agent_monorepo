"""非同期 SQLAlchemy エンジン + セッションファクトリ (PROPOSAL-0011 P2-B)。

`config.settings.resolved_database_url` から都度 URL を解決し、URL が変わったら
エンジンを作り直す (test isolation: 各テストが別の temp sqlite を使うため)。

- SQLite では WAL + foreign_keys を pragma で有効化。
- Postgres では pool_pre_ping を有効化 (Cloud SQL connector のアイドル切断対策)。
"""

from __future__ import annotations

import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

import config

logger = logging.getLogger(__name__)


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker | None = None
_engine_url: str | None = None


def _build_engine(url: str) -> AsyncEngine:
    engine = create_async_engine(
        url,
        future=True,
        echo=False,
        pool_pre_ping=not _is_sqlite(url),
    )
    if _is_sqlite(url):

        @event.listens_for(engine.sync_engine, "connect")
        def _on_connect(dbapi_connection, connection_record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA foreign_keys=ON;")
            finally:
                cursor.close()

    return engine


def get_engine() -> AsyncEngine:
    """resolved_database_url に対応するエンジンを返す (URL 変化で作り直す)。"""
    global _engine, _sessionmaker, _engine_url
    url = config.settings.resolved_database_url
    if _engine is None or _engine_url != url:
        # 旧エンジンは参照を落として GC に任せる (sync getter で await dispose 不可)。
        _engine = _build_engine(url)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
        _engine_url = url
        logger.debug("DB engine (re)built for url dialect=%s", url.split(":", 1)[0])
    return _engine


def get_sessionmaker() -> async_sessionmaker:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    """lifespan 終了時に pool を片付ける。"""
    global _engine, _sessionmaker, _engine_url
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
    _engine_url = None


__all__ = ["get_engine", "get_sessionmaker", "dispose_engine"]
