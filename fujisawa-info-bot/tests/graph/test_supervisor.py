"""build_graph + run_graph end-to-end のテスト。"""

from __future__ import annotations

from datetime import UTC, datetime

from fujisawa_platform.knowledge_base import (
    InMemoryStore,
    MockEmbeddingClient,
    PageDocument,
)
from llm_client import MockLLMClient

from app.graph import GraphDependencies, build_graph, run_graph


def _build_deps(*, fixed_reply: str) -> GraphDependencies:
    embedding = MockEmbeddingClient(dimension=64)
    store = InMemoryStore(embedding_dim=64)
    return GraphDependencies(
        llm=MockLLMClient(fixed_reply=fixed_reply),
        embedding=embedding,
        store=store,
        top_k=3,
    )


class TestRunGraph:
    async def test_empty_query_takes_out_of_scope_path(self) -> None:
        deps = _build_deps(fixed_reply='{"category":"other","confidence":0.9}')
        text = await run_graph(deps=deps, user_id="u1", query="")
        assert "範囲外" in text or "公式情報" in text

    async def test_rag_path_with_no_data(self) -> None:
        """category 分類は garbage、 でも store が空なので RAG fallback。"""
        deps = _build_deps(fixed_reply='{"category":"garbage","confidence":0.9}')
        text = await run_graph(deps=deps, user_id="u1", query="ゴミの日")
        assert "公式 HP から該当する情報が見つかりませんでした" in text

    async def test_out_of_scope_path_with_other_category(self) -> None:
        deps = _build_deps(fixed_reply='{"category":"other","confidence":0.9}')
        text = await run_graph(deps=deps, user_id="u1", query="こんにちは")
        assert "範囲外" in text

    async def test_full_rag_path_with_seeded_store(self) -> None:
        deps = _build_deps(fixed_reply='{"category":"garbage","confidence":0.9}')
        page = PageDocument(
            page_id="p1",
            url="https://www.city.fujisawa.kanagawa.jp/test",
            title="ゴミの日",
            content="月曜と木曜です。",
            embedding=deps.embedding.embed("ゴミ"),
            category="garbage",
            fetched_at=datetime.now(UTC),
        )
        await deps.store.upsert_page(page)
        text = await run_graph(deps=deps, user_id="u1", query="ゴミの日")
        # RAG ノードは LLM の fixed_reply (= JSON 文字列) をそのまま answer 本文として使う。
        # 出典フッタが必ず付与される。
        assert "出典:" in text
        assert "https://www.city.fujisawa.kanagawa.jp/test" in text


class TestBuildGraph:
    def test_compiled_graph_has_expected_nodes(self) -> None:
        deps = _build_deps(fixed_reply='{"category":"garbage","confidence":0.9}')
        compiled = build_graph(deps)
        # LangGraph compiled graph は `.nodes` を持つ
        node_keys = set(compiled.nodes.keys())
        assert {"classify", "rag", "out_of_scope"}.issubset(node_keys)
