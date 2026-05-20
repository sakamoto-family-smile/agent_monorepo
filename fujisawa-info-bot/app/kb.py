"""KnowledgeStore + EmbeddingClient ファクトリ。

`settings.kb_store_mode` と `settings.embedding_provider` を見て fujisawa-platform
の実装を組み立てる。 startup で 1 度だけ build して graph nodes に DI する。

pool / store の lifecycle:
- inmemory: stateless、 close 不要
- pgvector: asyncpg.Pool を返す → 呼び出し側でアプリ shutdown 時に `await pool.close()`
"""

from __future__ import annotations

from dataclasses import dataclass

from fujisawa_platform.knowledge_base import (
    EmbeddingClient,
    InMemoryStore,
    KnowledgeStore,
    MockEmbeddingClient,
)

from app.config import Settings


@dataclass
class KnowledgeBackend:
    """build_knowledge_backend の戻り値 — store + embedding + 任意の pool。"""

    store: KnowledgeStore
    embedding: EmbeddingClient
    pool: object | None = None  # asyncpg.Pool | None (lazy import 回避)


async def build_knowledge_backend(settings: Settings) -> KnowledgeBackend:
    """`settings.kb_store_mode` / `settings.embedding_provider` で組み立てる。

    pgvector / vertex は本番のみ。 default の inmemory + mock は同期だが、
    本番経路に合わせて async 関数として統一する。
    """
    embedding = _build_embedding(settings)

    if settings.kb_store_mode == "inmemory":
        store: KnowledgeStore = InMemoryStore(embedding_dim=embedding.dimension)
        return KnowledgeBackend(store=store, embedding=embedding, pool=None)

    if settings.kb_store_mode == "pgvector":
        from fujisawa_platform.knowledge_base import (
            PgvectorStore,
            build_pgvector_pool,
        )

        if not settings.cloud_sql_host or not settings.cloud_sql_user:
            raise RuntimeError(
                "CLOUD_SQL_HOST / CLOUD_SQL_USER are required for kb_store_mode=pgvector"
            )
        pool = await build_pgvector_pool(
            host=settings.cloud_sql_host,
            port=settings.cloud_sql_port,
            user=settings.cloud_sql_user,
            password=settings.cloud_sql_password,
            database=settings.cloud_sql_database,
        )
        pgvector_store = PgvectorStore(pool=pool, embedding_dim=embedding.dimension)
        return KnowledgeBackend(store=pgvector_store, embedding=embedding, pool=pool)

    raise ValueError(f"unknown kb_store_mode: {settings.kb_store_mode}")


def _build_embedding(settings: Settings) -> EmbeddingClient:
    if settings.embedding_provider == "mock":
        return MockEmbeddingClient(dimension=settings.embedding_dim)
    if settings.embedding_provider == "vertex":
        from fujisawa_platform.knowledge_base.embedding import VertexEmbeddingClient

        if not settings.gcp_project_id:
            raise RuntimeError(
                "FUJISAWA_INFO_BOT_GCP_PROJECT_ID is required for embedding_provider=vertex"
            )
        return VertexEmbeddingClient(
            project_id=settings.gcp_project_id,
            region=settings.vertex_region,
            dimension=settings.embedding_dim,
        )
    raise ValueError(f"unknown embedding_provider: {settings.embedding_provider}")


__all__ = ["KnowledgeBackend", "build_knowledge_backend"]
