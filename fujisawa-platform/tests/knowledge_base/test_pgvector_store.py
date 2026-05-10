"""PgvectorStore のテスト。

実 Cloud SQL は CI に持たないため、`asyncpg.Pool` / `Connection` を簡素な stub で
mock し、(1) SQL 文字列が期待通りであること、(2) 引数バインドが正しいこと、
(3) Record → PageDocument の round-trip が正しいことを検証する。

実 DB を使った接続テストは Phase 4 の ETL Cloud Run Jobs デプロイ時に手動 smoke
する想定 (proposal 0003 §4.6 Test Plan に準拠)。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import pytest

from fujisawa_platform.knowledge_base.pgvector_store import PgvectorStore
from fujisawa_platform.knowledge_base.store import PageDocument

# ─────────────────────────────────────────────────────────────────────
# asyncpg のミニマル stub
# ─────────────────────────────────────────────────────────────────────


class _StubConnection:
    """`pool.acquire()` で返ってくる接続の最小実装。

    実行された SQL / 引数を `executed` / `fetched` / `fetchrowed` に記録する。
    `register_vector` は no-op。
    """

    def __init__(
        self,
        *,
        execute_results: Iterable[str] = (),
        fetch_results: Iterable[list[dict[str, Any]]] = (),
        fetchrow_results: Iterable[dict[str, Any] | None] = (),
    ) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.fetched: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchrowed: list[tuple[str, tuple[Any, ...]]] = []
        self._execute_results = iter(execute_results)
        self._fetch_results = iter(fetch_results)
        self._fetchrow_results = iter(fetchrow_results)
        self.register_vector_calls = 0

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append((sql, args))
        try:
            return next(self._execute_results)
        except StopIteration:
            return "EXECUTE 1"

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.fetched.append((sql, args))
        try:
            return next(self._fetch_results)
        except StopIteration:
            return []

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.fetchrowed.append((sql, args))
        try:
            return next(self._fetchrow_results)
        except StopIteration:
            return None


class _StubAcquire:
    """`async with pool.acquire() as conn:` をサポートするコンテキスト。"""

    def __init__(self, conn: _StubConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> _StubConnection:
        return self._conn

    async def __aexit__(self, *_args: Any) -> None:
        return None


class _StubPool:
    def __init__(self, conn: _StubConnection) -> None:
        self._conn = conn
        self.acquired = 0

    def acquire(self) -> _StubAcquire:
        self.acquired += 1
        return _StubAcquire(self._conn)


def _make_page(
    *,
    page_id: str = "page-1",
    url: str = "https://www.city.fujisawa.kanagawa.jp/x.html",
    embedding: list[float] | None = None,
    category: str | None = "防災",
) -> PageDocument:
    return PageDocument(
        page_id=page_id,
        url=url,
        title="サンプル",
        content="本文",
        embedding=embedding if embedding is not None else [0.0] * 768,
        category=category,
        fetched_at=datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
        last_modified=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
    )


@pytest.fixture(autouse=True)
def _stub_register_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    """`pgvector.asyncpg.register_vector` を no-op に差し替える。

    pgvector パッケージが未インストールでも import エラーにならないよう、
    pgvector_store 内の参照を直接差し替える。
    """
    from fujisawa_platform.knowledge_base import pgvector_store

    async def _noop(_conn: Any) -> None:
        return None

    monkeypatch.setattr(pgvector_store, "_register_vector", _noop)


# ─────────────────────────────────────────────────────────────────────
# Construction
# ─────────────────────────────────────────────────────────────────────


class TestConstruction:
    def test_default_dim_is_768(self) -> None:
        store = PgvectorStore(pool=_StubPool(_StubConnection()))  # type: ignore[arg-type]
        assert store.embedding_dim == 768

    def test_custom_dim_accepted(self) -> None:
        store = PgvectorStore(pool=_StubPool(_StubConnection()), embedding_dim=384)  # type: ignore[arg-type]
        assert store.embedding_dim == 384

    def test_invalid_dim_rejected(self) -> None:
        with pytest.raises(ValueError, match="embedding_dim"):
            PgvectorStore(pool=_StubPool(_StubConnection()), embedding_dim=0)  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────
# upsert_page
# ─────────────────────────────────────────────────────────────────────


class TestUpsertPage:
    @pytest.mark.asyncio
    async def test_executes_insert_on_conflict(self) -> None:
        conn = _StubConnection()
        store = PgvectorStore(pool=_StubPool(conn))  # type: ignore[arg-type]
        page = _make_page()

        await store.upsert_page(page)

        assert len(conn.executed) == 1
        sql, args = conn.executed[0]
        assert "INSERT INTO pages" in sql
        assert "ON CONFLICT (page_id) DO UPDATE" in sql
        # params: page_id, url, title, content, embedding, category,
        #         fetched_at, last_modified, schema_version
        assert args[0] == "page-1"
        assert args[1] == "https://www.city.fujisawa.kanagawa.jp/x.html"
        assert args[2] == "サンプル"
        assert args[3] == "本文"
        assert args[4] == [0.0] * 768
        assert args[5] == "防災"
        assert isinstance(args[6], datetime)
        assert isinstance(args[7], datetime)
        assert args[8] == "v1"

    @pytest.mark.asyncio
    async def test_dimension_mismatch_rejected_before_db(self) -> None:
        conn = _StubConnection()
        store = PgvectorStore(pool=_StubPool(conn))  # type: ignore[arg-type]
        page = _make_page(embedding=[0.0] * 100)  # 100 != 768

        with pytest.raises(ValueError, match="dimension"):
            await store.upsert_page(page)

        assert conn.executed == []  # DB は叩かない

    @pytest.mark.asyncio
    async def test_optional_fields_passed_as_none(self) -> None:
        """title / category / last_modified が None でも UPSERT が通る。"""
        conn = _StubConnection()
        store = PgvectorStore(pool=_StubPool(conn))  # type: ignore[arg-type]
        page = PageDocument(
            page_id="page-2",
            url="https://www.city.fujisawa.kanagawa.jp/y.html",
            title=None,
            content="本文のみ",
            embedding=[0.0] * 768,
            category=None,
            fetched_at=datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
            last_modified=None,
        )

        await store.upsert_page(page)

        sql, args = conn.executed[0]
        assert args[2] is None  # title
        assert args[5] is None  # category
        assert args[7] is None  # last_modified


# ─────────────────────────────────────────────────────────────────────
# get_page
# ─────────────────────────────────────────────────────────────────────


def _row(
    *,
    page_id: str = "page-1",
    url: str = "https://www.city.fujisawa.kanagawa.jp/x.html",
    title: str | None = "サンプル",
    content: str = "本文",
    embedding: Any = None,
    category: str | None = "防災",
    fetched_at: datetime | None = None,
    last_modified: datetime | None = None,
    schema_version: str = "v1",
) -> dict[str, Any]:
    return {
        "page_id": page_id,
        "url": url,
        "title": title,
        "content": content,
        "embedding": embedding if embedding is not None else [0.0] * 768,
        "category": category,
        "fetched_at": fetched_at or datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
        "last_modified": last_modified or datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        "schema_version": schema_version,
    }


class TestGetPage:
    @pytest.mark.asyncio
    async def test_returns_page_when_found(self) -> None:
        conn = _StubConnection(fetchrow_results=[_row()])
        store = PgvectorStore(pool=_StubPool(conn))  # type: ignore[arg-type]

        page = await store.get_page("page-1")

        assert page is not None
        assert page.page_id == "page-1"
        assert page.title == "サンプル"
        assert page.embedding == [0.0] * 768
        sql, args = conn.fetchrowed[0]
        assert "FROM pages" in sql
        assert args == ("page-1",)

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        conn = _StubConnection(fetchrow_results=[None])
        store = PgvectorStore(pool=_StubPool(conn))  # type: ignore[arg-type]

        page = await store.get_page("missing")

        assert page is None

    @pytest.mark.asyncio
    async def test_numpy_embedding_normalized_to_list(self) -> None:
        """pgvector.asyncpg は numpy.ndarray を返すケースがあるので tolist() で list 化。"""

        class _FakeNDArray:
            def __init__(self, data: list[float]) -> None:
                self._data = data

            def tolist(self) -> list[float]:
                return self._data

        conn = _StubConnection(
            fetchrow_results=[_row(embedding=_FakeNDArray([0.1, 0.2, 0.3] + [0.0] * 765))],
        )
        store = PgvectorStore(pool=_StubPool(conn))  # type: ignore[arg-type]

        page = await store.get_page("page-1")
        assert page is not None
        assert isinstance(page.embedding, list)
        assert page.embedding[:3] == [0.1, 0.2, 0.3]


# ─────────────────────────────────────────────────────────────────────
# delete_page
# ─────────────────────────────────────────────────────────────────────


class TestDeletePage:
    @pytest.mark.asyncio
    async def test_returns_true_when_deleted(self) -> None:
        conn = _StubConnection(execute_results=["DELETE 1"])
        store = PgvectorStore(pool=_StubPool(conn))  # type: ignore[arg-type]

        result = await store.delete_page("page-1")

        assert result is True
        sql, args = conn.executed[0]
        assert "DELETE FROM pages" in sql
        assert args == ("page-1",)

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self) -> None:
        conn = _StubConnection(execute_results=["DELETE 0"])
        store = PgvectorStore(pool=_StubPool(conn))  # type: ignore[arg-type]

        result = await store.delete_page("missing")

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_status_unparseable(self) -> None:
        conn = _StubConnection(execute_results=["UNKNOWN"])
        store = PgvectorStore(pool=_StubPool(conn))  # type: ignore[arg-type]

        result = await store.delete_page("page-1")

        assert result is False


# ─────────────────────────────────────────────────────────────────────
# search_pages
# ─────────────────────────────────────────────────────────────────────


class TestSearchPages:
    @pytest.mark.asyncio
    async def test_orders_by_cosine_and_returns_score(self) -> None:
        rows = [
            {**_row(page_id="page-a"), "score": 0.95},
            {**_row(page_id="page-b"), "score": 0.82},
        ]
        conn = _StubConnection(fetch_results=[rows])
        store = PgvectorStore(pool=_StubPool(conn))  # type: ignore[arg-type]

        hits = await store.search_pages([0.0] * 768, top_k=2)

        assert [h.page.page_id for h in hits] == ["page-a", "page-b"]
        assert hits[0].score == pytest.approx(0.95)

        sql, args = conn.fetched[0]
        # cosine distance を 1 - distance で類似度に変換
        assert "1 - (embedding <=> $1) AS score" in sql
        assert "ORDER BY embedding <=> $1" in sql
        # params: query_embedding, category, top_k
        assert args[0] == [0.0] * 768
        assert args[1] is None
        assert args[2] == 2

    @pytest.mark.asyncio
    async def test_filters_by_category(self) -> None:
        conn = _StubConnection(fetch_results=[[]])
        store = PgvectorStore(pool=_StubPool(conn))  # type: ignore[arg-type]

        await store.search_pages([0.0] * 768, top_k=5, category="防災")

        _, args = conn.fetched[0]
        assert args[1] == "防災"

    @pytest.mark.asyncio
    async def test_dimension_mismatch_rejected_before_db(self) -> None:
        conn = _StubConnection()
        store = PgvectorStore(pool=_StubPool(conn))  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="dimension"):
            await store.search_pages([0.0] * 100, top_k=5)

        assert conn.fetched == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_rows(self) -> None:
        conn = _StubConnection(fetch_results=[[]])
        store = PgvectorStore(pool=_StubPool(conn))  # type: ignore[arg-type]

        hits = await store.search_pages([0.0] * 768)

        assert hits == []
