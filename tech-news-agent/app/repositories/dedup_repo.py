"""配信済み記事の dedup + digest メタ情報の永続化 (SQLite + aiosqlite)。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class DedupRepo:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._initialized = False

    @asynccontextmanager
    async def _conn(self) -> AsyncIterator[aiosqlite.Connection]:
        conn = await aiosqlite.connect(self._db_path)
        try:
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA foreign_keys=ON;")
            yield conn
        finally:
            await conn.close()

    async def initialize(self) -> None:
        if self._initialized:
            return
        if ":memory:" not in self._db_path:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        ddl = _SCHEMA_PATH.read_text(encoding="utf-8")
        async with self._conn() as conn:
            await conn.executescript(ddl)
            await conn.commit()
        self._initialized = True

    async def filter_new_ids(
        self, article_ids: Iterable[str], *, window_days: int
    ) -> set[str]:
        """配信済みでない article_id の集合を返す。

        `window_days` 以前の delivered は除外 (昔すぎる記事は再配信しても良い)。
        """
        ids = list(dict.fromkeys(article_ids))  # 順序維持の uniq
        if not ids:
            return set()
        cutoff = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()
        placeholders = ",".join("?" * len(ids))
        sql = (
            "SELECT article_id FROM delivered_articles "
            f"WHERE article_id IN ({placeholders}) AND delivered_at >= ?"
        )
        async with self._conn() as conn:
            async with conn.execute(sql, (*ids, cutoff)) as cur:
                delivered = {row[0] async for row in cur}
        return set(ids) - delivered

    async def create_digest(self, digest_id: str, *, generated_at: datetime) -> None:
        async with self._conn() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO digests "
                "(digest_id, generated_at, delivered_at, status, article_count, line_status_note) "
                "VALUES (?, ?, NULL, 'pending', 0, NULL)",
                (digest_id, generated_at.isoformat()),
            )
            await conn.commit()

    async def record_delivery(
        self,
        *,
        digest_id: str,
        articles: list[tuple[str, str, str, str, str]],  # (article_id,title,source_name,source_type,url_normalized)
        status: str,
        note: str | None = None,
    ) -> None:
        """配信結果を SQLite に記録。status='sent'/'failed'。"""
        now_iso = datetime.now(UTC).isoformat()
        async with self._conn() as conn:
            await conn.execute(
                "UPDATE digests SET delivered_at = ?, status = ?, article_count = ?, "
                "line_status_note = ? WHERE digest_id = ?",
                (now_iso, status, len(articles), note, digest_id),
            )
            if status == "sent" and articles:
                await conn.executemany(
                    "INSERT OR IGNORE INTO delivered_articles "
                    "(article_id, title, source_name, source_type, url_normalized, "
                    " delivered_at, digest_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (aid, title, source, stype, url_norm, now_iso, digest_id)
                        for (aid, title, source, stype, url_norm) in articles
                    ],
                )
            await conn.commit()

    async def count_delivered(self) -> int:
        async with self._conn() as conn:
            async with conn.execute("SELECT COUNT(*) FROM delivered_articles") as cur:
                row = await cur.fetchone()
                return int(row[0]) if row else 0
