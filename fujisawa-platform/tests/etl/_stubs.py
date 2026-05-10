"""ETL テスト共通の asyncpg.Pool / Connection の最小 stub。

Phase 4-1 の `test_pgvector_store.py` 内 `_StubConnection` を
ETL 全 Job のテストで共有するために切り出したもの。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class StubConnection:
    """`pool.acquire()` で返ってくる接続の最小実装。

    実行された SQL / 引数を `executed` / `fetched` / `fetchrowed` に記録する。
    """

    def __init__(
        self,
        *,
        execute_results: Iterable[str] = (),
        fetch_results: Iterable[list[dict[str, Any]]] = (),
        fetchrow_results: Iterable[dict[str, Any] | None] = (),
    ) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.fetched: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchrowed: list[tuple[str, tuple[Any, ...]]] = []
        self._execute_results = iter(execute_results)
        self._fetch_results = iter(fetch_results)
        self._fetchrow_results = iter(fetchrow_results)

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append((sql, args))
        try:
            return next(self._execute_results)
        except StopIteration:
            return "EXECUTE 1"

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.fetched.append((sql, args))
        try:
            return next(self._fetch_results)
        except StopIteration:
            return []

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.fetchrowed.append((sql, args))
        try:
            return next(self._fetchrow_results)
        except StopIteration:
            return None


class _StubAcquire:
    def __init__(self, conn: StubConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> StubConnection:
        return self._conn

    async def __aexit__(self, *_args: Any) -> None:
        return None


class StubPool:
    """`async with pool.acquire() as conn:` をサポートする最小 Pool。"""

    def __init__(self, conn: StubConnection) -> None:
        self._conn = conn
        self.acquired = 0

    def acquire(self) -> _StubAcquire:
        self.acquired += 1
        return _StubAcquire(self._conn)
