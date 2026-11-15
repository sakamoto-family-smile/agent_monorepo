"""ops.db_copy (DB の全件コピーと照合、PROPOSAL-0013) のテスト。

SQLite 同士は常に実行する。Postgres との往復は `STOCK_TEST_POSTGRES_URL`
(例: postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/postgres) があるときだけ実行する。
"""

from __future__ import annotations

import asyncio
import os

import pytest
from ops import db_copy
from services.db_models import (
    EdinetDocument,
    PriceCache,
    Report,
    TickerDictionary,
    WatchlistItem,
)
from sqlalchemy import insert, select, text, update
from sqlalchemy.ext.asyncio import create_async_engine

PG_URL = os.getenv("STOCK_TEST_POSTGRES_URL", "")


def _sqlite(tmp_path, name: str) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / name}"


def _run(coro):
    return asyncio.run(coro)


async def _exec(url: str, *stmts) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for stmt in stmts:
                await conn.execute(stmt)
    finally:
        await engine.dispose()


async def _scalars(url: str, stmt):
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(stmt)).scalars().all()
    finally:
        await engine.dispose()


def _seed(url: str) -> None:
    _run(
        _exec(
            url,
            insert(Report).values(id=1, ticker="7203.T", company_name="トヨタ", report_data='{"a": 1}'),
            insert(Report).values(id=5, ticker="AAPL", company_name=None, report_data="長い本文" * 100),
            insert(WatchlistItem).values(id=3, user_id="U1", ticker="7203.T", name="トヨタ"),
            insert(TickerDictionary).values(id=2, company_name="任天堂", ticker="7974.T"),
            insert(EdinetDocument).values(
                document_id="S100ABCD",
                edinet_code="E02144",
                submitter_name="トヨタ自動車",
                document_type="120",
                submit_date="2026-06-20",
            ),
            insert(PriceCache).values(ticker="7203.T", period="3mo", data="[]", expires_at="2099-01-01"),
        )
    )


def _seed_reports_only(url: str) -> None:
    _run(_exec(url, insert(Report).values(id=1, ticker="7203.T", report_data="{}")))


def _copy(src: str, dst: str, *, force: bool = False, include_cache: bool = False, batch_size: int = 500):
    db_copy.upgrade_schema(dst)
    tables = db_copy.target_tables(include_cache=include_cache)

    async def go():
        s, d = create_async_engine(src), create_async_engine(dst)
        try:
            copied = await db_copy.copy_all(s, d, tables, force=force, batch_size=batch_size)
            return copied, await db_copy.verify(s, d, tables)
        finally:
            await s.dispose()
            await d.dispose()

    return _run(go())


@pytest.fixture
def src(tmp_path) -> str:
    url = _sqlite(tmp_path, "src.db")
    db_copy.upgrade_schema(url)
    _seed(url)
    return url


def test_copies_all_tables_and_verifies(src, tmp_path):
    dst = _sqlite(tmp_path, "dst.db")

    copied, reports = _copy(src, dst, batch_size=1)

    assert copied["reports"] == 2
    assert copied["watchlist"] == 1
    assert copied["edinet_documents"] == 1
    assert all(r.ok for r in reports)
    assert _run(_scalars(dst, select(Report.id).order_by(Report.id))) == [1, 5]


def test_skips_price_cache_by_default(src, tmp_path):
    dst = _sqlite(tmp_path, "dst.db")

    copied, _ = _copy(src, dst)

    assert "price_cache" not in copied
    assert _run(_scalars(dst, select(PriceCache.id))) == []


def test_include_cache_copies_price_cache(src, tmp_path):
    dst = _sqlite(tmp_path, "dst.db")

    copied, reports = _copy(src, dst, include_cache=True)

    assert copied["price_cache"] == 1
    assert all(r.ok for r in reports)


def test_refuses_non_empty_destination_without_force(src, tmp_path):
    dst = _sqlite(tmp_path, "dst.db")
    db_copy.upgrade_schema(dst)
    _seed_reports_only(dst)

    with pytest.raises(db_copy.CopyError, match="--force"):
        _copy(src, dst)
    # 何も書き換えていない
    assert _run(_scalars(dst, select(Report.id))) == [1]


def test_force_replaces_destination_rows(src, tmp_path):
    dst = _sqlite(tmp_path, "dst.db")
    db_copy.upgrade_schema(dst)
    _run(_exec(dst, insert(Report).values(id=99, ticker="OLD", report_data="{}")))

    _, reports = _copy(src, dst, force=True)

    assert all(r.ok for r in reports)
    assert _run(_scalars(dst, select(Report.id).order_by(Report.id))) == [1, 5]


def test_refuses_mismatched_alembic_revision(src, tmp_path):
    dst = _sqlite(tmp_path, "dst.db")
    db_copy.upgrade_schema(dst)
    _run(_exec(src, text("UPDATE alembic_version SET version_num = '0002_edinet_documents'")))

    with pytest.raises(db_copy.CopyError, match="リビジョン"):
        _copy(src, dst)


def test_verify_detects_changed_row(src, tmp_path):
    dst = _sqlite(tmp_path, "dst.db")
    _copy(src, dst)
    _run(_exec(dst, update(Report).where(Report.id == 5).values(report_data="改ざん")))

    async def go():
        s, d = create_async_engine(src), create_async_engine(dst)
        try:
            return await db_copy.verify(s, d, db_copy.target_tables(include_cache=False))
        finally:
            await s.dispose()
            await d.dispose()

    reports = {r.name: r for r in _run(go())}
    assert not reports["reports"].ok
    assert reports["reports"].src_rows == reports["reports"].dst_rows
    assert reports["watchlist"].ok


def test_main_returns_nonzero_on_mismatch(src, tmp_path, monkeypatch, capsys):
    dst = _sqlite(tmp_path, "dst.db")
    _copy(src, dst)
    _run(_exec(dst, update(Report).where(Report.id == 1).values(ticker="X")))
    monkeypatch.setenv("SRC_DATABASE_URL", src)
    monkeypatch.setenv("DST_DATABASE_URL", dst)

    assert db_copy.main(["--verify-only"]) == 1
    assert "NG" in capsys.readouterr().out


def test_main_rejects_same_src_and_dst(src):
    with pytest.raises(SystemExit):
        db_copy.main(["--src", src, "--dst", src])


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite:///data/x.db", "sqlite+aiosqlite:///data/x.db"),
        ("postgresql://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("postgres://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("postgresql+asyncpg://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
    ],
)
def test_normalize_url(url, expected):
    assert db_copy.normalize_url(url) == expected


def test_redact_url_hides_password():
    assert db_copy.redact_url("postgresql+asyncpg://user:s3cr@t@/db?host=/cloudsql/x") == (
        "postgresql+asyncpg://user:***@/db?host=/cloudsql/x"
    )
    assert db_copy.redact_url("sqlite+aiosqlite:///a.db") == "sqlite+aiosqlite:///a.db"


@pytest.mark.skipif(not PG_URL, reason="STOCK_TEST_POSTGRES_URL が未設定")
def test_roundtrip_with_postgres_keeps_rows_and_fixes_sequences(src, tmp_path):
    _run(_exec(PG_URL, text("DROP SCHEMA public CASCADE"), text("CREATE SCHEMA public")))

    _, to_pg = _copy(src, PG_URL)
    assert all(r.ok for r in to_pg)

    # 連番が max(id) + 1 に合っていれば、id を指定しない INSERT が衝突しない
    _run(_exec(PG_URL, insert(Report).values(ticker="NEW", report_data="{}")))
    assert _run(_scalars(PG_URL, select(Report.id).where(Report.ticker == "NEW"))) == [6]

    back = _sqlite(tmp_path, "back.db")
    _, to_sqlite = _copy(PG_URL, back)
    assert all(r.ok for r in to_sqlite)
    assert _run(_scalars(back, select(Report.id).order_by(Report.id))) == [1, 5, 6]
