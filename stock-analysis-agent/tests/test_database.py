"""SQLAlchemy DB 層 (PROPOSAL-0011 P2-B) のユニットテスト (SQLite)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
async def db(tmp_path: Path, monkeypatch):
    """temp SQLite を使う DB を初期化し、エンジンを片付ける。"""
    import config
    from services import database
    from services.db_engine import dispose_engine

    await dispose_engine()
    monkeypatch.setattr(config.settings, "database_url", "", raising=False)
    monkeypatch.setattr(config.settings, "db_host", "", raising=False)
    monkeypatch.setattr(config.settings, "db_path", str(tmp_path / "t.db"), raising=False)
    monkeypatch.setattr(config.settings, "db_auto_create", True, raising=False)
    await database.init_db()
    yield database
    await dispose_engine()


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------


async def test_save_and_get_reports_roundtrip(db):
    rid = await db.save_report("7203.T", "トヨタ", {"report_text": "強気", "score": 1})
    assert isinstance(rid, int) and rid > 0

    reports = await db.get_reports("7203.T", limit=10)
    assert len(reports) == 1
    r = reports[0]
    assert r["ticker"] == "7203.T"
    assert r["company_name"] == "トヨタ"
    # report_data は JSON 文字列のまま返す (route が json.loads する契約)
    assert isinstance(r["report_data"], str)
    assert json.loads(r["report_data"])["report_text"] == "強気"


async def test_get_reports_orders_desc_and_limits(db):
    for i in range(3):
        await db.save_report("AAPL", "Apple", {"n": i})
    reports = await db.get_reports("AAPL", limit=2)
    assert len(reports) == 2
    # 最新 (id 降順) が先頭
    assert json.loads(reports[0]["report_data"])["n"] == 2


# ---------------------------------------------------------------------------
# price_cache
# ---------------------------------------------------------------------------


async def test_price_cache_set_get_roundtrip(db):
    data = [{"date": "2026-01-01", "close": 100.0}]
    await db.set_cached_price("AAPL", "3mo", data)
    got = await db.get_cached_price("AAPL", "3mo")
    assert got == data


async def test_price_cache_upsert_replaces(db):
    await db.set_cached_price("AAPL", "3mo", [{"v": 1}])
    await db.set_cached_price("AAPL", "3mo", [{"v": 2}])
    got = await db.get_cached_price("AAPL", "3mo")
    assert got == [{"v": 2}]


async def test_price_cache_expired_returns_none(db, monkeypatch):
    import config

    # TTL を負にして即時失効させる
    monkeypatch.setattr(config.settings, "price_cache_ttl_hours", -1, raising=False)
    await db.set_cached_price("AAPL", "1d", [{"v": 1}])
    assert await db.get_cached_price("AAPL", "1d") is None


async def test_price_cache_miss_returns_none(db):
    assert await db.get_cached_price("UNKNOWN", "3mo") is None


# ---------------------------------------------------------------------------
# ticker dictionary (seed + alias)
# ---------------------------------------------------------------------------


async def test_lookup_ticker_exact_match_from_seed(db):
    row = await db.lookup_ticker("トヨタ")
    assert row is not None
    assert row["ticker"] == "7203.T"


async def test_lookup_ticker_alias_match(db):
    row = await db.lookup_ticker("toyota")  # seed の alias
    assert row is not None
    assert row["ticker"] == "7203.T"


async def test_lookup_ticker_unknown_returns_none(db):
    assert await db.lookup_ticker("存在しない会社XYZ") is None


async def test_seed_is_idempotent(db):
    # init_db を再度呼んでも辞書は重複しない
    await db.init_db()
    row = await db.lookup_ticker("ソニー")
    assert row is not None and row["ticker"] == "6758.T"


# ---------------------------------------------------------------------------
# resolved_database_url
# ---------------------------------------------------------------------------


def test_resolved_url_prefers_database_url(monkeypatch):
    import config

    monkeypatch.setattr(config.settings, "database_url", "postgresql+asyncpg://x/y")
    assert config.settings.resolved_database_url == "postgresql+asyncpg://x/y"


def test_resolved_url_builds_postgres_from_parts(monkeypatch):
    import config

    s = config.settings
    monkeypatch.setattr(s, "database_url", "")
    monkeypatch.setattr(s, "db_host", "/cloudsql/p:r:shared-pg")
    monkeypatch.setattr(s, "db_user", "stock_analysis_user")
    monkeypatch.setattr(s, "db_name", "stock_analysis_db")
    monkeypatch.setattr(s, "db_password", "p@ss/w:rd")
    url = s.resolved_database_url
    assert url.startswith("postgresql+asyncpg://stock_analysis_user:")
    # 特殊文字は percent-encode される
    assert "p%40ss%2Fw%3Ard@" in url
    assert "host=/cloudsql/p:r:shared-pg" in url


def test_resolved_url_falls_back_to_sqlite(monkeypatch):
    import config

    s = config.settings
    monkeypatch.setattr(s, "database_url", "")
    monkeypatch.setattr(s, "db_host", "")
    monkeypatch.setattr(s, "db_path", "data/x.db")
    assert s.resolved_database_url == "sqlite+aiosqlite:///data/x.db"


# ---------------------------------------------------------------------------
# watchlist (PROPOSAL-0012)
# ---------------------------------------------------------------------------


async def test_watchlist_add_get_remove_roundtrip(db):
    assert await db.add_watchlist_item("U_a", "7203.T", "トヨタ") is True
    assert await db.add_watchlist_item("U_a", "AAPL", "Apple") is True
    items = await db.get_watchlist("U_a")
    assert [i["ticker"] for i in items] == ["AAPL", "7203.T"]  # 新しい順
    assert items[0]["name"] == "Apple"
    assert await db.count_watchlist("U_a") == 2

    assert await db.remove_watchlist_item("U_a", "AAPL") is True
    assert [i["ticker"] for i in await db.get_watchlist("U_a")] == ["7203.T"]


async def test_watchlist_add_is_idempotent(db):
    assert await db.add_watchlist_item("U_a", "7203.T", "トヨタ") is True
    assert await db.add_watchlist_item("U_a", "7203.T", "トヨタ") is False  # 重複
    assert await db.count_watchlist("U_a") == 1


async def test_watchlist_remove_missing_returns_false(db):
    assert await db.remove_watchlist_item("U_a", "NOPE") is False


async def test_watchlist_is_per_user(db):
    await db.add_watchlist_item("U_a", "7203.T", "トヨタ")
    await db.add_watchlist_item("U_b", "AAPL", "Apple")
    assert [i["ticker"] for i in await db.get_watchlist("U_a")] == ["7203.T"]
    assert [i["ticker"] for i in await db.get_watchlist("U_b")] == ["AAPL"]
    assert await db.count_watchlist("U_a") == 1
