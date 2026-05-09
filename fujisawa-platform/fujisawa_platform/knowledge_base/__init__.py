"""knowledge_base: ベクトル検索基盤。

Vertex AI text-embedding-004 (768 dim) + Cloud SQL Postgres + pgvector で
HTML page / PDF chunk の類似検索を行う。

driving-license-bot の pattern を踏襲し、Embedding は Protocol 抽象化。
本番は VertexEmbeddingClient、テストは MockEmbeddingClient。
"""

from fujisawa_platform.knowledge_base.embedding import (
    EmbeddingClient,
    MockEmbeddingClient,
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
    "SearchHit",
]
