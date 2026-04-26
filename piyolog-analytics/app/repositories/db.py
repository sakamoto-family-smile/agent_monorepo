"""非同期 DB エンジン + セッションファクトリ。

`DATABASE_URL` で SQLite (dev/test) と Postgres (prod) を切替:
  - sqlite+aiosqlite:///./data/piyolog.db
  - postgresql+asyncpg://user:pass@host:5432/dbname

`piyolog_db_path` (旧 env) も後方互換で受ける: 値があれば自動的に
sqlite+aiosqlite URL に変換する。

設計:
  - エンジンは `create_engine_for(url)` で都度生成する pure な関数。
    アプリは lifespan で 1 度だけ作って `EventRepo` に渡す。
  - SQLite では WAL + foreign_keys を pragma で有効化。Postgres では何もしない。
  - `dispose_engine()` で接続プールを片付ける (lifespan 終了時に呼ぶ)。
"""

from __future__ import annotations

import logging
from typing import Final

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)


SQLITE_DIALECT_PREFIX: Final[str] = "sqlite"


def _is_sqlite(url: str) -> bool:
    return url.startswith(SQLITE_DIALECT_PREFIX)


def normalize_database_url(url: str | None, *, fallback_sqlite_path: str | None = None) -> str:
    """`DATABASE_URL` または `piyolog_db_path` から正規化 URL を返す。

    優先度: 引数 url > fallback_sqlite_path → sqlite+aiosqlite:///{path}
    どちらも空なら `:memory:` SQLite (テスト想定)。
    """
    if url:
        return url
    if fallback_sqlite_path:
        return f"sqlite+aiosqlite:///{fallback_sqlite_path}"
    return "sqlite+aiosqlite:///:memory:"


def create_engine_for(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """非同期エンジンを作る。SQLite は pragma 設定込み。"""
    engine = create_async_engine(
        database_url,
        echo=echo,
        future=True,
        # SQLite の :memory: + 並列接続は state を共有しないため、テストで使う際は
        # 単一プロセス前提でプールサイズを抑える。
        pool_pre_ping=not _is_sqlite(database_url),
    )
    if _is_sqlite(database_url):
        _attach_sqlite_pragmas(engine)
    return engine


def _attach_sqlite_pragmas(engine: AsyncEngine) -> None:
    """新規接続ごとに WAL + foreign_keys を有効化する。"""

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection, connection_record):  # noqa: ANN001 - SQLAlchemy hook
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
        finally:
            cursor.close()


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def dispose_engine(engine: AsyncEngine) -> None:
    """lifespan 終了時に呼んで pool を片付ける。"""
    await engine.dispose()
