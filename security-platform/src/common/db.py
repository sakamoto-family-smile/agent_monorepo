"""運用 DB (SQLite) への接続。

- 書き込み側は WAL モード + busy_timeout で開く (他プロセスの読み取りと共存させる)
- 他サブシステムの DB は ``mode=ro`` の URI で開き、誤って書けないようにする
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event

BUSY_TIMEOUT_MS = 30_000


def _on_connect(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    cur.execute("PRAGMA foreign_keys = ON")
    cur.close()


def _on_connect_writer(dbapi_conn, record) -> None:
    _on_connect(dbapi_conn, record)
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL")
    cur.execute("PRAGMA synchronous = NORMAL")
    cur.close()


def make_engine(path: Path, *, read_only: bool = False) -> Engine:
    """SQLite ファイルへの Engine を返す。read_only=True ならファイルが無ければ失敗する。"""
    if read_only:
        if not path.exists():
            raise FileNotFoundError(path)
        url = f"sqlite:///file:{path}?mode=ro&uri=true"
        engine = create_engine(url)
        event.listen(engine, "connect", _on_connect)
        return engine
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    event.listen(engine, "connect", _on_connect_writer)
    return engine
