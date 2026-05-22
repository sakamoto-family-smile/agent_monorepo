"""knowledge_base: ベクトル検索基盤。

Vertex AI text-embedding-004 (768 dim) + Cloud SQL Postgres + pgvector で
HTML page / PDF chunk の類似検索を行う。

driving-license-bot の pattern を踏襲し、Embedding は Protocol 抽象化。
本番は VertexEmbeddingClient、テストは MockEmbeddingClient。

Store 実装:
- `InMemoryStore`: 開発・テスト用 (dict ベース、cosine = 内積で full scan)
- `PgvectorStore`: 本番用 (asyncpg + pgvector、`uv sync --extra pgvector` で導入)
"""

from fujisawa_platform.knowledge_base.embedding import (
    EmbeddingClient,
    MockEmbeddingClient,
    VertexEmbeddingClient,
)
from fujisawa_platform.knowledge_base.pgvector_store import (
    PgvectorStore,
    build_pgvector_pool,
)
from fujisawa_platform.knowledge_base.store import (
    InMemoryStore,
    KnowledgeStore,
    PageDocument,
    SearchHit,
)

__all__ = [
    "EmbeddingClient",
    "InMemoryStore",
    "KnowledgeStore",
    "MockEmbeddingClient",
    "PageDocument",
    "PgvectorStore",
    "SearchHit",
    "VertexEmbeddingClient",
    "build_pgvector_pool",
]
