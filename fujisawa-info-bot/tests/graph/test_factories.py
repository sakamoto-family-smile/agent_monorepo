"""build_llm_client / build_knowledge_backend のテスト。"""

from __future__ import annotations

import pytest
from fujisawa_platform.knowledge_base import InMemoryStore, MockEmbeddingClient
from llm_client import MockLLMClient

from app.config import Settings
from app.kb import build_knowledge_backend
from app.llm import build_llm_client


class TestBuildLLMClient:
    def test_mock_provider_returns_mock_llm(self) -> None:
        settings = Settings(llm_provider="mock")
        client = build_llm_client(settings)
        assert isinstance(client, MockLLMClient)

    def test_vertex_provider_requires_project_id(self) -> None:
        settings = Settings(llm_provider="vertex_anthropic", gcp_project_id="")
        with pytest.raises(RuntimeError, match="GCP_PROJECT_ID"):
            build_llm_client(settings)


class TestBuildKnowledgeBackend:
    async def test_inmemory_default_uses_mock_embedding(self) -> None:
        settings = Settings(
            kb_store_mode="inmemory", embedding_provider="mock", embedding_dim=64
        )
        backend = await build_knowledge_backend(settings)
        assert isinstance(backend.store, InMemoryStore)
        assert isinstance(backend.embedding, MockEmbeddingClient)
        assert backend.pool is None

    async def test_pgvector_requires_cloud_sql_host(self) -> None:
        settings = Settings(
            kb_store_mode="pgvector",
            embedding_provider="mock",
            cloud_sql_host="",
        )
        with pytest.raises(RuntimeError, match="CLOUD_SQL_HOST"):
            await build_knowledge_backend(settings)
