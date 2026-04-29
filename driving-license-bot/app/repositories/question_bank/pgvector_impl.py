"""pgvector ベースの Question Bank（Cloud SQL Postgres 本番用）。

依存: `pgvector` extra (`uv sync --extra pgvector`)
- asyncpg
- pgvector

Phase 2-D では実 Cloud SQL への接続テストは CI で行わない。インスタンスを
立てた後に手動で `scripts/init_question_bank_schema.py`（PR E で追加予定）等で
スキーマを作成し、`QUESTION_BANK_BACKEND=pgvector` で起動する想定。

スキーマ:
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE TABLE questions (
        question_id     TEXT PRIMARY KEY,
        version         INTEGER NOT NULL,
        body_hash       TEXT NOT NULL,
        embedding       vector(768) NOT NULL,
        applicable_goals TEXT[] NOT NULL,
        category        TEXT NOT NULL,
        difficulty      TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'needs_review',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX questions_embedding_ivfflat ON questions
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
    CREATE INDEX questions_body_hash_idx ON questions (body_hash);
    CREATE INDEX questions_status_idx ON questions (status);
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.agent.errors import LLMClientError
from app.repositories.question_bank.protocol import (
    SimilarityHit,
    StoredQuestion,
)

if TYPE_CHECKING:  # pragma: no cover — 型ヒント専用
    import asyncpg

logger = logging.getLogger(__name__)


class PgvectorQuestionBank:
    """asyncpg + pgvector による Question Bank。

    プールはアプリ起動時に外部で構築し、本クラスに asyncpg.Pool を渡す形にする
    （短命接続を避け、Cloud SQL の同時接続上限を保護）。
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def add(self, question: StoredQuestion) -> None:
        async with self._pool.acquire() as conn:
            await self._register_vector(conn)
            await conn.execute(
                """
                INSERT INTO questions (
                    question_id, version, body_hash, embedding,
                    applicable_goals, category, difficulty, status, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (question_id) DO UPDATE SET
                    version = EXCLUDED.version,
                    body_hash = EXCLUDED.body_hash,
                    embedding = EXCLUDED.embedding,
                    applicable_goals = EXCLUDED.applicable_goals,
                    category = EXCLUDED.category,
                    difficulty = EXCLUDED.difficulty,
                    status = EXCLUDED.status
                """,
                question.question_id,
                question.version,
                question.body_hash,
                question.embedding,
                question.applicable_goals,
                question.category,
                question.difficulty,
                question.status,
                question.created_at,
            )

    async def find_similar(
        self,
        embedding: list[float],
        *,
        top_k: int = 5,
        category: str | None = None,
    ) -> list[SimilarityHit]:
        # cosine 距離を 1 - cos_distance で類似度に変換
        async with self._pool.acquire() as conn:
            await self._register_vector(conn)
            sql = """
                SELECT
                    question_id, version, body_hash, embedding,
                    applicable_goals, category, difficulty, status, created_at,
                    1 - (embedding <=> $1) AS score
                FROM questions
                WHERE ($2::text IS NULL OR category = $2)
                ORDER BY embedding <=> $1
                LIMIT $3
            """
            rows = await conn.fetch(sql, embedding, category, top_k)
        return [SimilarityHit(stored=_row_to_stored(r), score=float(r["score"])) for r in rows]

    async def find_by_body_hash(self, body_hash: str) -> StoredQuestion | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM questions WHERE body_hash = $1 LIMIT 1",
                body_hash,
            )
        return _row_to_stored(row) if row else None

    async def count(
        self,
        *,
        status: str | None = None,
        applicable_goal: str | None = None,
    ) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS c FROM questions
                WHERE ($1::text IS NULL OR status = $1)
                  AND ($2::text IS NULL OR $2 = ANY(applicable_goals))
                """,
                status,
                applicable_goal,
            )
        return int(row["c"]) if row else 0

    async def get(self, question_id: str) -> StoredQuestion | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM questions WHERE question_id = $1",
                question_id,
            )
        return _row_to_stored(row) if row else None

    async def list_by_status(
        self,
        status: str,
        *,
        limit: int = 50,
    ) -> list[StoredQuestion]:
        async with self._pool.acquire() as conn:
            await self._register_vector(conn)
            rows = await conn.fetch(
                """
                SELECT
                    question_id, version, body_hash, embedding,
                    applicable_goals, category, difficulty, status, created_at
                FROM questions
                WHERE status = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                status,
                limit,
            )
        return [_row_to_stored(r) for r in rows]

    async def update_status(self, question_id: str, status: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE questions SET status = $1 WHERE question_id = $2",
                status,
                question_id,
            )
        # asyncpg の execute は "UPDATE N" を返す。N=0 なら未更新。
        try:
            n = int(result.split()[-1])
        except (ValueError, IndexError):
            return False
        return n > 0

    async def _register_vector(self, conn: asyncpg.Connection) -> None:
        """pgvector の型コーデックをコネクションに登録する。"""
        try:
            from pgvector.asyncpg import register_vector
        except ImportError as exc:  # pragma: no cover — pgvector 未インストール時
            raise LLMClientError(
                "pgvector package is required (install with `uv sync --extra pgvector`)"
            ) from exc
        await register_vector(conn)


def _row_to_stored(row: dict[str, Any] | None) -> StoredQuestion:
    """asyncpg Record / dict → StoredQuestion。"""
    if row is None:
        raise ValueError("row is None")
    embedding = row["embedding"]
    # pgvector.asyncpg は numpy.ndarray を返すため list 化
    if hasattr(embedding, "tolist"):
        embedding = embedding.tolist()
    return StoredQuestion(
        question_id=row["question_id"],
        version=row["version"],
        body_hash=row["body_hash"],
        embedding=list(embedding),
        applicable_goals=list(row["applicable_goals"]),
        category=row["category"],
        difficulty=row["difficulty"],
        status=row["status"],
        created_at=_coerce_dt(row["created_at"]),
    )


def _coerce_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


async def build_pgvector_pool(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    min_size: int = 1,
    max_size: int = 5,
) -> asyncpg.Pool:
    """asyncpg.Pool を作成する補助関数（テストでは未使用）。

    Cloud SQL Auth Proxy 経由なら host="127.0.0.1" を渡す。
    """
    try:
        import asyncpg
    except ImportError as exc:  # pragma: no cover
        raise LLMClientError(
            "asyncpg is required (install with `uv sync --extra pgvector`)"
        ) from exc
    return await asyncpg.create_pool(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        min_size=min_size,
        max_size=max_size,
    )


__all__ = ["PgvectorQuestionBank", "build_pgvector_pool"]
