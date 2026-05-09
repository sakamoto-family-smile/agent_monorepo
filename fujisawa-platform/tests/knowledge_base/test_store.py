"""KnowledgeStore (pgvector の抽象化) のテスト。

実 Postgres は CI で動かさない (本番疎通 smoke は別途)。
本テストは Protocol 契約と InMemoryStore (Mock) の挙動を検証する。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fujisawa_platform.knowledge_base.embedding import MockEmbeddingClient
from fujisawa_platform.knowledge_base.store import (
    InMemoryStore,
    KnowledgeStore,
    PageDocument,
)


@pytest.fixture
def store() -> KnowledgeStore:
    return InMemoryStore(embedding_dim=768)


@pytest.fixture
def embedder() -> MockEmbeddingClient:
    return MockEmbeddingClient()


def _make_page(
    *,
    page_id: str,
    url: str,
    content: str,
    embedding: list[float],
    category: str | None = None,
) -> PageDocument:
    return PageDocument(
        page_id=page_id,
        url=url,
        title=f"title for {page_id}",
        content=content,
        embedding=embedding,
        category=category,
        fetched_at=datetime(2026, 5, 9, tzinfo=UTC),
        last_modified=None,
    )


class TestProtocol:
    def test_in_memory_satisfies_protocol(self, store: KnowledgeStore) -> None:
        assert isinstance(store, KnowledgeStore)


class TestUpsertAndGet:
    @pytest.mark.asyncio
    async def test_upsert_and_get_by_id(
        self, store: KnowledgeStore, embedder: MockEmbeddingClient
    ) -> None:
        page = _make_page(
            page_id="page-1",
            url="https://www.city.fujisawa.kanagawa.jp/a",
            content="鵠沼地区のゴミ収集",
            embedding=embedder.embed("鵠沼地区のゴミ収集"),
        )
        await store.upsert_page(page)
        retrieved = await store.get_page("page-1")
        assert retrieved is not None
        assert retrieved.page_id == "page-1"
        assert retrieved.content == "鵠沼地区のゴミ収集"

    @pytest.mark.asyncio
    async def test_get_returns_none_for_unknown_id(self, store: KnowledgeStore) -> None:
        assert await store.get_page("nonexistent") is None

    @pytest.mark.asyncio
    async def test_upsert_replaces_existing(
        self, store: KnowledgeStore, embedder: MockEmbeddingClient
    ) -> None:
        page = _make_page(
            page_id="page-1",
            url="https://www.city.fujisawa.kanagawa.jp/a",
            content="original",
            embedding=embedder.embed("original"),
        )
        await store.upsert_page(page)

        updated = _make_page(
            page_id="page-1",
            url="https://www.city.fujisawa.kanagawa.jp/a",
            content="updated",
            embedding=embedder.embed("updated"),
        )
        await store.upsert_page(updated)

        retrieved = await store.get_page("page-1")
        assert retrieved is not None
        assert retrieved.content == "updated"


class TestSearch:
    @pytest.mark.asyncio
    async def test_finds_most_similar(
        self, store: KnowledgeStore, embedder: MockEmbeddingClient
    ) -> None:
        """同じ入力で embed したクエリは元の page を最高 score で返す。"""
        target = _make_page(
            page_id="page-1",
            url="https://www.city.fujisawa.kanagawa.jp/a",
            content="鵠沼地区のゴミ収集スケジュール",
            embedding=embedder.embed("鵠沼地区のゴミ収集スケジュール"),
        )
        decoy = _make_page(
            page_id="page-2",
            url="https://www.city.fujisawa.kanagawa.jp/b",
            content="保育園の入所申込",
            embedding=embedder.embed("保育園の入所申込"),
        )
        await store.upsert_page(target)
        await store.upsert_page(decoy)

        query_vec = embedder.embed("鵠沼地区のゴミ収集スケジュール")
        results = await store.search_pages(query_vec, top_k=2)

        assert len(results) == 2
        assert results[0].page.page_id == "page-1"
        assert results[0].score > results[1].score
        # 完全一致クエリは score ≈ 1.0
        assert results[0].score > 0.99

    @pytest.mark.asyncio
    async def test_top_k_limits_results(
        self, store: KnowledgeStore, embedder: MockEmbeddingClient
    ) -> None:
        for i in range(5):
            await store.upsert_page(
                _make_page(
                    page_id=f"page-{i}",
                    url=f"https://www.city.fujisawa.kanagawa.jp/{i}",
                    content=f"content {i}",
                    embedding=embedder.embed(f"content {i}"),
                )
            )
        results = await store.search_pages(embedder.embed("query"), top_k=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_filter_by_category(
        self, store: KnowledgeStore, embedder: MockEmbeddingClient
    ) -> None:
        await store.upsert_page(
            _make_page(
                page_id="bosai-1",
                url="https://www.city.fujisawa.kanagawa.jp/bosai/a",
                content="防災情報",
                embedding=embedder.embed("防災情報"),
                category="防災",
            )
        )
        await store.upsert_page(
            _make_page(
                page_id="gomi-1",
                url="https://www.city.fujisawa.kanagawa.jp/gomi/a",
                content="ゴミ収集",
                embedding=embedder.embed("ゴミ収集"),
                category="ゴミ",
            )
        )

        results = await store.search_pages(
            embedder.embed("query"), top_k=10, category="防災"
        )
        assert len(results) == 1
        assert results[0].page.category == "防災"

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty(
        self, store: KnowledgeStore, embedder: MockEmbeddingClient
    ) -> None:
        results = await store.search_pages(embedder.embed("nothing"), top_k=10)
        assert results == []


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_removes_page(
        self, store: KnowledgeStore, embedder: MockEmbeddingClient
    ) -> None:
        page = _make_page(
            page_id="page-1",
            url="https://www.city.fujisawa.kanagawa.jp/a",
            content="x",
            embedding=embedder.embed("x"),
        )
        await store.upsert_page(page)
        assert await store.get_page("page-1") is not None

        deleted = await store.delete_page("page-1")
        assert deleted is True
        assert await store.get_page("page-1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, store: KnowledgeStore) -> None:
        assert await store.delete_page("nonexistent") is False


class TestEmbeddingDimensionMismatch:
    @pytest.mark.asyncio
    async def test_rejects_wrong_dimension(self, store: KnowledgeStore) -> None:
        bad_vec = [0.1] * 256  # store は 768 dim
        page = _make_page(
            page_id="page-1",
            url="https://www.city.fujisawa.kanagawa.jp/a",
            content="x",
            embedding=bad_vec,
        )
        with pytest.raises(ValueError, match="dimension"):
            await store.upsert_page(page)
