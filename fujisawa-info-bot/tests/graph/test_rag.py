"""answer_with_rag (rag.py) のテスト。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fujisawa_platform.knowledge_base import (
    InMemoryStore,
    MockEmbeddingClient,
    PageDocument,
)
from llm_client import MockLLMClient

from app.graph.agents.rag import answer_with_rag

_FIXED_REPLY = "回答: 鵠沼は月・木です。"


@pytest.fixture
def embedding() -> MockEmbeddingClient:
    return MockEmbeddingClient(dimension=64)


@pytest.fixture
def store(embedding: MockEmbeddingClient) -> InMemoryStore:
    return InMemoryStore(embedding_dim=embedding.dimension)


def _page(*, page_id: str, url: str, title: str, content: str, embedding_vec: list[float]) -> PageDocument:
    return PageDocument(
        page_id=page_id,
        url=url,
        title=title,
        content=content,
        embedding=embedding_vec,
        category="garbage",
        fetched_at=datetime.now(UTC),
    )


class TestAnswerWithRAG:
    async def test_empty_query_returns_fallback(
        self, embedding: MockEmbeddingClient, store: InMemoryStore
    ) -> None:
        text, hits = await answer_with_rag(
            query="   ",
            embedding=embedding,
            store=store,
            llm=MockLLMClient(fixed_reply=_FIXED_REPLY),
            top_k=3,
        )
        assert hits == []
        assert "公式 HP から該当する情報が見つかりませんでした" in text

    async def test_no_hit_returns_fallback(
        self, embedding: MockEmbeddingClient, store: InMemoryStore
    ) -> None:
        text, hits = await answer_with_rag(
            query="ゴミ",
            embedding=embedding,
            store=store,
            llm=MockLLMClient(fixed_reply=_FIXED_REPLY),
            top_k=3,
        )
        assert hits == []
        assert "公式 HP から該当する情報が見つかりませんでした" in text

    async def test_single_hit_includes_llm_body_and_citation(
        self, embedding: MockEmbeddingClient, store: InMemoryStore
    ) -> None:
        page = _page(
            page_id="p1",
            url="https://www.city.fujisawa.kanagawa.jp/garbage1",
            title="ゴミ収集カレンダー",
            content="鵠沼地区は燃えるゴミが月・木曜日です。",
            embedding_vec=embedding.embed("ゴミ"),
        )
        await store.upsert_page(page)
        text, hits = await answer_with_rag(
            query="ゴミの日",
            embedding=embedding,
            store=store,
            llm=MockLLMClient(fixed_reply=_FIXED_REPLY),
            top_k=3,
        )
        assert len(hits) == 1
        assert _FIXED_REPLY in text
        assert "出典:" in text
        assert "https://www.city.fujisawa.kanagawa.jp/garbage1" in text

    async def test_multiple_hits_dedupe_urls(
        self, embedding: MockEmbeddingClient, store: InMemoryStore
    ) -> None:
        # 同じ URL で 2 ページ (例: 異なる title だが同一 URL は実運用では稀)
        same_url = "https://www.city.fujisawa.kanagawa.jp/same"
        await store.upsert_page(
            _page(
                page_id="p1",
                url=same_url,
                title="A",
                content="A の内容",
                embedding_vec=embedding.embed("A"),
            )
        )
        await store.upsert_page(
            _page(
                page_id="p2",
                url=same_url,
                title="B",
                content="B の内容",
                embedding_vec=embedding.embed("B"),
            )
        )
        text, _ = await answer_with_rag(
            query="A",
            embedding=embedding,
            store=store,
            llm=MockLLMClient(fixed_reply=_FIXED_REPLY),
            top_k=5,
        )
        # 出典は重複除外 → URL 出現は 1 回
        assert text.count(same_url) == 1

    async def test_caps_citations_to_three(
        self, embedding: MockEmbeddingClient, store: InMemoryStore
    ) -> None:
        for i in range(5):
            await store.upsert_page(
                _page(
                    page_id=f"p{i}",
                    url=f"https://www.city.fujisawa.kanagawa.jp/p{i}",
                    title=f"title-{i}",
                    content=f"content-{i}",
                    embedding_vec=embedding.embed(f"query-{i}"),
                )
            )
        text, hits = await answer_with_rag(
            query="query-0",
            embedding=embedding,
            store=store,
            llm=MockLLMClient(fixed_reply=_FIXED_REPLY),
            top_k=5,
        )
        # フッタ部分の "・" 出現数 ≤ 3
        footer = text.split("出典:", 1)[1]
        assert footer.count("・") <= 3

    async def test_llm_failure_falls_back_to_citation_only(
        self, embedding: MockEmbeddingClient, store: InMemoryStore
    ) -> None:
        class _Bad:
            async def complete(self, *, system, user, cache_system=False) -> str:  # noqa: D401
                raise RuntimeError("vertex outage")

            async def complete_messages(self, *, system, messages, cache_system=False) -> str:
                raise RuntimeError("unused")

        await store.upsert_page(
            _page(
                page_id="p1",
                url="https://www.city.fujisawa.kanagawa.jp/x",
                title="t",
                content="c",
                embedding_vec=embedding.embed("x"),
            )
        )
        text, hits = await answer_with_rag(
            query="x",
            embedding=embedding,
            store=store,
            llm=_Bad(),  # type: ignore[arg-type]
            top_k=3,
        )
        assert len(hits) == 1
        assert "情報を整理する処理が失敗しました" in text
        assert "https://www.city.fujisawa.kanagawa.jp/x" in text

    async def test_category_filter_is_passed_to_store(
        self, embedding: MockEmbeddingClient, store: InMemoryStore
    ) -> None:
        # 違う category を入れる
        page_garbage = _page(
            page_id="g1",
            url="https://www.city.fujisawa.kanagawa.jp/garbage",
            title="garbage",
            content="garbage",
            embedding_vec=embedding.embed("garbage"),
        )
        # disaster category として直接入れる
        page_disaster = PageDocument(
            page_id="d1",
            url="https://www.city.fujisawa.kanagawa.jp/disaster",
            title="disaster",
            content="disaster",
            embedding=embedding.embed("disaster"),
            category="disaster",
            fetched_at=datetime.now(UTC),
        )
        await store.upsert_page(page_garbage)
        await store.upsert_page(page_disaster)

        text, hits = await answer_with_rag(
            query="garbage",
            embedding=embedding,
            store=store,
            llm=MockLLMClient(fixed_reply=_FIXED_REPLY),
            top_k=5,
            category="disaster",
        )
        # disaster カテゴリのみが返る
        assert all(h.page.category == "disaster" for h in hits)
