"""マイリスト LINE コマンド (PROPOSAL-0012) のハンドラテスト。

実 DB (temp sqlite) を使い、resolve_ticker / search_candidates はスタブ化する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import config
from services import line_handler
from services.line_client import LineTextEvent

pytestmark = pytest.mark.asyncio


class _StubClient:
    def __init__(self):
        self.replies = []

    async def reply_text(self, *, reply_token, text):
        self.replies.append({"type": "text", "text": text})

    async def reply_flex(self, *, reply_token, alt_text, contents):
        self.replies.append({"type": "flex", "alt_text": alt_text, "contents": contents})

    async def push_text(self, *, to, text):
        pass

    async def push_flex(self, *, to, alt_text, contents):
        pass

    async def close(self):
        pass


def _deps(client):
    return line_handler.HandlerDeps(line_client=client, schedule_background=lambda f: None)


def _ev(text, user_id="U_a"):
    return LineTextEvent(
        event_type="text", line_user_id=user_id, reply_token="rt", text=text
    )


@pytest.fixture
async def db(tmp_path: Path, monkeypatch):
    from services import database
    from services.db_engine import dispose_engine

    await dispose_engine()
    monkeypatch.setattr(config.settings, "database_url", "", raising=False)
    monkeypatch.setattr(config.settings, "db_host", "", raising=False)
    monkeypatch.setattr(config.settings, "db_path", str(tmp_path / "w.db"), raising=False)
    monkeypatch.setattr(config.settings, "db_auto_create", True, raising=False)
    await database.init_db()
    yield database
    await dispose_engine()


def _stub_resolve(monkeypatch, *, ticker, name, source="dict"):
    from models.stock import ResolveResult

    async def _r(query):
        return ResolveResult(ticker=ticker, confidence=0.9, source=source, company_name=name)

    monkeypatch.setattr(line_handler, "resolve_ticker", _r)


# ---------------------------------------------------------------------------
# 追加
# ---------------------------------------------------------------------------


async def test_add_confident_then_show_then_remove(db, monkeypatch):
    _stub_resolve(monkeypatch, ticker="7203.T", name="トヨタ")
    client = _StubClient()
    await line_handler._cmd_watchlist_add(["トヨタ"], _ev("追加 トヨタ"), _deps(client))
    assert any("追加しました" in r["text"] and "7203.T" in r["text"] for r in client.replies)
    assert [i["ticker"] for i in await db.get_watchlist("U_a")] == ["7203.T"]

    # 一覧 (Flex)
    client2 = _StubClient()
    await line_handler._cmd_watchlist_show(_ev("マイリスト"), _deps(client2))
    assert client2.replies[0]["type"] == "flex"
    assert "7203.T" in str(client2.replies[0]["contents"])

    # 削除
    _stub_resolve(monkeypatch, ticker="7203.T", name="トヨタ")
    client3 = _StubClient()
    await line_handler._cmd_watchlist_remove(["7203.T"], _ev("削除 7203.T"), _deps(client3))
    assert any("削除しました" in r["text"] for r in client3.replies)
    assert await db.get_watchlist("U_a") == []


async def test_add_duplicate_notifies(db, monkeypatch):
    _stub_resolve(monkeypatch, ticker="AAPL", name="Apple")
    client = _StubClient()
    await line_handler._cmd_watchlist_add(["AAPL"], _ev("追加 AAPL"), _deps(client))
    await line_handler._cmd_watchlist_add(["AAPL"], _ev("追加 AAPL"), _deps(client))
    assert any("すでにマイリストにあります" in r["text"] for r in client.replies)
    assert await db.count_watchlist("U_a") == 1


async def test_add_ambiguous_shows_candidates_with_add_command(db, monkeypatch):
    from agents.ticker_resolver import TickerCandidate
    from models.stock import ResolveResult

    async def _low(query):
        return ResolveResult(ticker=query.upper(), confidence=0.3, source="llm", company_name=query)

    monkeypatch.setattr(line_handler, "resolve_ticker", _low)
    monkeypatch.setattr(
        line_handler,
        "search_candidates",
        lambda q: [TickerCandidate(ticker="7203.T", name="トヨタ自動車")],
    )
    client = _StubClient()
    await line_handler._cmd_watchlist_add(["とよた"], _ev("追加 とよた"), _deps(client))
    # 候補 Flex、ボタンは「追加 <ticker>」
    assert client.replies[0]["type"] == "flex"
    assert "追加 7203.T" in str(client.replies[0]["contents"])
    # まだ登録されていない
    assert await db.get_watchlist("U_a") == []


async def test_add_over_limit_rejected(db, monkeypatch):
    monkeypatch.setattr(config.settings, "watchlist_max_items", 2)
    _stub_resolve(monkeypatch, ticker="AAA", name="A")
    await db.add_watchlist_item("U_a", "X1", "x")
    await db.add_watchlist_item("U_a", "X2", "x")
    client = _StubClient()
    await line_handler._cmd_watchlist_add(["AAA"], _ev("追加 AAA"), _deps(client))
    assert any("上限" in r["text"] for r in client.replies)
    assert await db.count_watchlist("U_a") == 2


async def test_remove_missing(db, monkeypatch):
    _stub_resolve(monkeypatch, ticker="ZZZ", name=None)
    client = _StubClient()
    await line_handler._cmd_watchlist_remove(["ZZZ"], _ev("削除 ZZZ"), _deps(client))
    assert any("見つかりませんでした" in r["text"] for r in client.replies)


async def test_remove_stale_entry_by_raw_input(db, monkeypatch):
    """正規化後 ticker と異なる旧データ (例: .T 無しの 285A) も生入力で削除できる。

    JPX 新形式コード対応前に登録された「285A」は、対応後は resolve が
    「285A.T」を返すため正規化 ticker では一致しない。生入力フォールバックで救済する。
    """
    # 旧データを直接投入 (.T 無し)
    await db.add_watchlist_item("U_a", "285A", None)
    # 対応後の resolve は 285A.T を返す
    _stub_resolve(monkeypatch, ticker="285A.T", name="キオクシア", source="regex")

    client = _StubClient()
    await line_handler._cmd_watchlist_remove(["285A"], _ev("削除 285A"), _deps(client))
    assert any("削除しました" in r["text"] for r in client.replies)
    assert await db.get_watchlist("U_a") == []


async def test_show_empty_guides(db):
    client = _StubClient()
    await line_handler._cmd_watchlist_show(_ev("マイリスト"), _deps(client))
    assert any("空" in r["text"] for r in client.replies)


# ---------------------------------------------------------------------------
# スクリーニング マイ
# ---------------------------------------------------------------------------


async def test_screen_my_empty_guides(db):
    client = _StubClient()
    await line_handler._cmd_screen(["マイ"], _ev("スクリーニング マイ"), _deps(client))
    assert any("マイリストが空" in r["text"] for r in client.replies)


async def test_screen_my_uses_watchlist_tickers(db, monkeypatch):
    await db.add_watchlist_item("U_a", "7203.T", "トヨタ")
    await db.add_watchlist_item("U_a", "6758.T", "ソニー")

    captured = {}

    from models.stock import ScreenerResult

    async def _fake_run(req):
        captured["tickers"] = req.tickers
        captured["market"] = req.market
        return ScreenerResult(market=req.market, total_scanned=2, candidates=[])

    monkeypatch.setattr(line_handler, "run_screener", _fake_run)
    client = _StubClient()
    await line_handler._cmd_screen(["マイ"], _ev("スクリーニング マイ"), _deps(client))
    assert captured["market"] == "MY"
    assert sorted(captured["tickers"]) == ["6758.T", "7203.T"]


# ---------------------------------------------------------------------------
# 企業名の補完 (ティッカー追加時)
# ---------------------------------------------------------------------------


async def test_add_by_ticker_enriches_name(db, monkeypatch):
    """ティッカーで追加 (名前なし解決) でも企業名が補完されて保存される。"""
    from models.stock import ResolveResult

    async def _regex(query):
        return ResolveResult(
            ticker="7203.T", confidence=0.95, source="regex", company_name=None
        )

    monkeypatch.setattr(line_handler, "resolve_ticker", _regex)
    monkeypatch.setattr(line_handler, "fetch_ticker_name", lambda t: "トヨタ自動車")

    client = _StubClient()
    await line_handler._cmd_watchlist_add(["7203.T"], _ev("追加 7203.T"), _deps(client))

    items = await db.get_watchlist("U_a")
    assert items[0]["ticker"] == "7203.T"
    assert items[0]["name"] == "トヨタ自動車"
    assert any("トヨタ自動車" in r["text"] for r in client.replies)


async def test_add_by_ticker_name_lookup_failure_falls_back(db, monkeypatch):
    """名前補完が失敗 (None) でもティッカーで登録できる。"""
    from models.stock import ResolveResult

    async def _regex(query):
        return ResolveResult(
            ticker="ZZZZ", confidence=0.95, source="regex", company_name=None
        )

    monkeypatch.setattr(line_handler, "resolve_ticker", _regex)
    monkeypatch.setattr(line_handler, "fetch_ticker_name", lambda t: None)

    client = _StubClient()
    await line_handler._cmd_watchlist_add(["ZZZZ"], _ev("追加 ZZZZ"), _deps(client))
    items = await db.get_watchlist("U_a")
    assert items[0]["ticker"] == "ZZZZ"
    assert items[0]["name"] is None
