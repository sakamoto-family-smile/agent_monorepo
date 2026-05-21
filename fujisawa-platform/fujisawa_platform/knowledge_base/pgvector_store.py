"""PgvectorStore: asyncpg + pgvector ベースの本番 KnowledgeStore 実装。

依存: `pgvector` extra (`uv sync --extra pgvector`)
- asyncpg
- pgvector

設計上の選択 (proposal 0003 §4.3 / §4.5.5 / driving-license-bot pattern 流用):
- `asyncpg.Pool` は本クラスの外で構築 → 短命接続を避け、Cloud SQL の同時接続上限を保護
- 1 クエリごとに `pgvector.asyncpg.register_vector()` を呼ぶ (driving-license-bot と同じ)
  → Pool から acquire した接続は再利用されるが、初回のみ register が必要なため毎回呼んで no-op にする
- cosine 距離は pgvector の `<=>` 演算子 / 類似度は `1 - (<=>)`
- 本番 import (asyncpg / pgvector) は呼出時 lazy: import 失敗時は明示的なエラーを返す
- `pages` テーブルのみ対応 (proposal 0003 §4.3)。`pdf_documents` は別 PR

実 Cloud SQL への接続テストは Phase 4 ETL Cloud Run Jobs デプロイ時の手動 smoke で行う
(proposal 0003 §4.6 Test Plan)。本ファイルの単体テストは asyncpg を mock したもの。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from fujisawa_platform.knowledge_base.store import PageDocument, SearchHit

if TYPE_CHECKING:  # pragma: no cover — 型ヒント専用
    import asyncpg


class PgvectorStore:
    """`KnowledgeStore` Protocol の本番実装。

    Example:
        pool = await build_pgvector_pool(host=..., user=..., database="fujisawa_kb_db")
        store = PgvectorStore(pool=pool, embedding_dim=768)
        await store.upsert_page(page)
    """

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        embedding_dim: int = 768,
    ) -> None:
        if embedding_dim < 1:
            raise ValueError("embedding_dim must be >= 1")
        self._pool = pool
        self._dim = embedding_dim

    @property
    def embedding_dim(self) -> int:
        return self._dim

    async def upsert_page(self, page: PageDocument) -> None:
        if len(page.embedding) != self._dim:
            raise ValueError(
                f"embedding dimension mismatch: expected {self._dim}, got {len(page.embedding)}"
            )
        async with self._pool.acquire() as conn:
            await _register_vector(conn)
            await conn.execute(
                """
                INSERT INTO pages (
                    page_id, url, title, content, embedding,
                    category, fetched_at, last_modified, schema_version
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (page_id) DO UPDATE SET
                    url = EXCLUDED.url,
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding,
                    category = EXCLUDED.category,
                    fetched_at = EXCLUDED.fetched_at,
                    last_modified = EXCLUDED.last_modified,
                    schema_version = EXCLUDED.schema_version
                """,
                page.page_id,
                str(page.url),
                page.title,
                page.content,
                page.embedding,
                page.category,
                page.fetched_at,
                page.last_modified,
                page.schema_version,
            )

    async def get_page(self, page_id: str) -> PageDocument | None:
        async with self._pool.acquire() as conn:
            await _register_vector(conn)
            row = await conn.fetchrow(
                """
                SELECT
                    page_id, url, title, content, embedding,
                    category, fetched_at, last_modified, schema_version
                FROM pages
                WHERE page_id = $1
                """,
                page_id,
            )
        return _row_to_page(row) if row else None

    async def delete_page(self, page_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM pages WHERE page_id = $1",
                page_id,
            )
        # asyncpg の execute は "DELETE N" を返す。N=0 なら未削除。
        try:
            n = int(result.split()[-1])
        except (ValueError, IndexError):
            return False
        return n > 0

    async def get_last_modified_map(
        self, urls: list[str]
    ) -> dict[str, datetime | None]:
        """指定 URL の `last_modified` を一括取得 (差分 crawl 用)。

        urls が空なら DB を叩かずに空 dict を返す。 N+1 を避けるため
        `WHERE url = ANY($1::text[])` で一発取得する。
        """
        if not urls:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT url, last_modified FROM pages WHERE url = ANY($1::text[])",
                urls,
            )
        return {row["url"]: _coerce_dt_optional(row["last_modified"]) for row in rows}

    async def search_pages(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 10,
        category: str | None = None,
    ) -> list[SearchHit]:
        if len(query_embedding) != self._dim:
            raise ValueError(
                f"query embedding dimension mismatch: expected {self._dim}, "
                f"got {len(query_embedding)}"
            )
        async with self._pool.acquire() as conn:
            await _register_vector(conn)
            rows = await conn.fetch(
                """
                SELECT
                    page_id, url, title, content, embedding,
                    category, fetched_at, last_modified, schema_version,
                    1 - (embedding <=> $1) AS score
                FROM pages
                WHERE ($2::text IS NULL OR category = $2)
                ORDER BY embedding <=> $1
                LIMIT $3
                """,
                query_embedding,
                category,
                top_k,
            )
        return [SearchHit(page=_row_to_page(r), score=float(r["score"])) for r in rows]


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


async def _register_vector(conn: asyncpg.Connection) -> None:
    """pgvector の型コーデックを接続に登録する。

    pgvector パッケージ未インストール時は呼出時に分かりやすいエラーを出す
    (lazy import)。
    """
    try:
        from pgvector.asyncpg import register_vector
    except ImportError as exc:  # pragma: no cover — pgvector 未インストール時
        raise RuntimeError(
            "pgvector package is required (install with `uv sync --extra pgvector`)"
        ) from exc
    await register_vector(conn)


def _row_to_page(row: Any) -> PageDocument:
    """asyncpg.Record / dict → PageDocument。

    pgvector.asyncpg は numpy.ndarray を返すため `tolist()` で list 化する。
    """
    embedding = row["embedding"]
    if hasattr(embedding, "tolist"):
        embedding = embedding.tolist()
    return PageDocument(
        page_id=row["page_id"],
        url=row["url"],
        title=row["title"],
        content=row["content"],
        embedding=list(embedding),
        category=row["category"],
        fetched_at=_coerce_dt(row["fetched_at"]),
        last_modified=_coerce_dt_optional(row["last_modified"]),
        schema_version=row["schema_version"],
    )


def _coerce_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _coerce_dt_optional(value: Any) -> datetime | None:
    if value is None:
        return None
    return _coerce_dt(value)


async def build_pgvector_pool(
    *,
    host: str,
    port: int = 5432,
    user: str,
    password: str,
    database: str,
    min_size: int = 1,
    max_size: int = 5,
) -> asyncpg.Pool:
    """asyncpg.Pool を構築する補助関数。

    Cloud SQL Auth Proxy 経由なら `host="127.0.0.1"` を渡す。
    呼出側 (consumer agent / ETL Job) のライフサイクルでクローズすること。
    """
    try:
        import asyncpg
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("asyncpg is required (install with `uv sync --extra pgvector`)") from exc
    return await asyncpg.create_pool(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        min_size=min_size,
        max_size=max_size,
    )


__all__ = ["PgvectorStore", "build_pgvector_pool"]
