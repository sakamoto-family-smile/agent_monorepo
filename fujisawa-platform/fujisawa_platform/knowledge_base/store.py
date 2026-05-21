"""KnowledgeStore: pgvector の Repository 抽象。

Protocol で定義し、本番は asyncpg + pgvector の実装、テストは InMemoryStore で
deterministic に検証する。

Phase 2 範囲: pages テーブル (sitemap.xml クロール結果) のみ対応。
pdf_documents は Phase 2.5 で対応 (Docling との統合後)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class PageDocument(BaseModel):
    """pages テーブルの 1 行に対応 (proposal 0003 §4.3)。"""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    page_id: str = Field(min_length=1)
    url: HttpUrl
    title: str | None = None
    content: str
    embedding: list[float]
    category: str | None = None
    fetched_at: datetime
    last_modified: datetime | None = None
    schema_version: str = "v1"


@dataclass(frozen=True)
class SearchHit:
    """検索結果 (page + cosine score)。"""

    page: PageDocument
    score: float  # 0.0〜1.0、cosine 類似度


@runtime_checkable
class KnowledgeStore(Protocol):
    """pages テーブルへの async CRUD + ベクトル検索。"""

    async def upsert_page(self, page: PageDocument) -> None: ...

    async def get_page(self, page_id: str) -> PageDocument | None: ...

    async def delete_page(self, page_id: str) -> bool: ...

    async def search_pages(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 10,
        category: str | None = None,
    ) -> list[SearchHit]: ...

    async def get_last_modified_map(
        self, urls: list[str]
    ) -> dict[str, datetime | None]: ...


class InMemoryStore:
    """テスト・ローカル開発用の in-memory 実装。

    本番は `PgvectorStore` (Phase 2.x で追加) に差し替える。
    """

    def __init__(self, *, embedding_dim: int = 768) -> None:
        if embedding_dim < 1:
            raise ValueError("embedding_dim must be >= 1")
        self._dim = embedding_dim
        self._pages: dict[str, PageDocument] = {}

    async def upsert_page(self, page: PageDocument) -> None:
        if len(page.embedding) != self._dim:
            raise ValueError(
                f"embedding dimension mismatch: expected {self._dim}, "
                f"got {len(page.embedding)}"
            )
        self._pages[page.page_id] = page

    async def get_page(self, page_id: str) -> PageDocument | None:
        return self._pages.get(page_id)

    async def delete_page(self, page_id: str) -> bool:
        return self._pages.pop(page_id, None) is not None

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

        candidates = (
            (page, _cosine(query_embedding, page.embedding))
            for page in self._pages.values()
            if category is None or page.category == category
        )
        sorted_hits = sorted(candidates, key=lambda kv: kv[1], reverse=True)
        return [SearchHit(page=p, score=s) for p, s in sorted_hits[:top_k]]

    async def get_last_modified_map(
        self, urls: list[str]
    ) -> dict[str, datetime | None]:
        """指定 URL の `last_modified` を一括取得 (差分 crawl 用)。

        - 指定 URL が pages テーブルに無ければ key 不在 (initial crawl 用)
        - last_modified カラムが NULL のときは value=None を返す
          ↳ consumer 側で「DB に row はあるが last_modified 不明」 として再 fetch 判定
        """
        target = set(urls)
        result: dict[str, datetime | None] = {}
        for page in self._pages.values():
            url_str = str(page.url)
            if url_str in target:
                result[url_str] = page.last_modified
        return result


def _cosine(a: list[float], b: list[float]) -> float:
    """正規化済ベクトルなら内積、そうでなくても cosine を計算。"""
    if len(a) != len(b):
        raise ValueError(f"vector dim mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    denom = norm_a * norm_b
    if denom == 0:
        return 0.0
    return dot / denom
