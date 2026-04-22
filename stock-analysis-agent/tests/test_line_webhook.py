"""LINE Bot Webhook (/api/line/webhook) と `line_handler` の統合テスト。

方針:
  - LINE SDK は叩かず `StubLineBotClient` を `set_line_bot_client` で差し込む
  - 個別株分析 (`分析 X`) は実 Claude を呼ばないよう analyze_runner をモックする
  - スクリーナー / ファンドレコメンドは yfinance を _download_batch でモックする
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from unittest.mock import patch

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Stub LINE client
# ---------------------------------------------------------------------------


class StubLineBotClient:
    def __init__(self) -> None:
        self.events_to_return: list = []
        self.raise_signature: bool = False
        self.replies: list[dict] = []
        self.pushes: list[dict] = []
        self.fail_flex: bool = False
        self.fail_push_flex: bool = False
        self.close_called: bool = False

    def parse_events(self, *, body: bytes, signature: str):
        from services.line_client import InvalidSignatureError

        if self.raise_signature:
            raise InvalidSignatureError("stub: bad signature")
        return list(self.events_to_return)

    async def reply_text(self, *, reply_token: str, text: str) -> None:
        self.replies.append(
            {"type": "text", "reply_token": reply_token, "text": text}
        )

    async def reply_flex(
        self, *, reply_token: str, alt_text: str, contents: dict
    ) -> None:
        if self.fail_flex:
            raise RuntimeError("stub: flex disabled")
        self.replies.append(
            {
                "type": "flex",
                "reply_token": reply_token,
                "text": alt_text,
                "alt_text": alt_text,
                "contents": contents,
            }
        )

    async def push_text(self, *, to: str, text: str) -> None:
        self.pushes.append({"type": "text", "to": to, "text": text})

    async def push_flex(self, *, to: str, alt_text: str, contents: dict) -> None:
        if self.fail_push_flex:
            raise RuntimeError("stub: push flex disabled")
        self.pushes.append(
            {
                "type": "flex",
                "to": to,
                "alt_text": alt_text,
                "text": alt_text,
                "contents": contents,
            }
        )

    async def close(self) -> None:
        self.close_called = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CHARTS_DIR", str(tmp_path / "charts"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("DICTIONARIES_DIR", str(tmp_path / "dictionaries"))
    monkeypatch.setenv("ANALYTICS_DATA_DIR", str(tmp_path / "analytics"))


@pytest.fixture
def stub():
    from services.line_client import set_line_bot_client

    s = StubLineBotClient()
    set_line_bot_client(s)
    yield s
    set_line_bot_client(None)


@pytest.fixture
async def client(_env):
    import importlib
    import config
    importlib.reload(config)
    import instrumentation
    instrumentation.setup_observability()
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await instrumentation.shutdown_observability()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text_event(text: str, *, user_id: str = "U_alice", reply_token: str = "rt"):
    from services.line_client import LineTextEvent

    return LineTextEvent(
        event_type="text", line_user_id=user_id, reply_token=reply_token, text=text
    )


async def _post_webhook(client: AsyncClient, body: bytes = b'{"events":[]}') -> dict:
    r = await client.post(
        "/api/line/webhook",
        content=body,
        headers={"X-Line-Signature": "stub", "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _make_uptrend_df(n: int = 260) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    closes = [100.0 * (1 + 0.05 / 100.0) ** i for i in range(n)]
    return pd.DataFrame(
        {
            "Open": closes, "High": closes, "Low": closes,
            "Close": closes, "Volume": [1_000_000] * n,
        },
        index=dates,
    )


def _make_screener_bullish_df(n: int = 60) -> pd.DataFrame:
    """test_screener.py の `_make_deterministic_bullish_df` と等価な形状。"""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    closes: list[float] = []
    base = 1000.0
    for i in range(n - 5):
        closes.append(base - i * 5.0)
    for _ in range(5):
        closes.append(closes[-1] + 1.5)
    avg_volume = 100_000
    volumes = [avg_volume] * n
    volumes[-1] = avg_volume * 3
    return pd.DataFrame(
        {
            "Open": [c * 0.99 for c in closes],
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.98 for c in closes],
            "Close": closes,
            "Volume": volumes,
        },
        index=dates,
    )


# ---------------------------------------------------------------------------
# Route-level: 503 / 401 / 200
# ---------------------------------------------------------------------------


async def test_webhook_returns_503_when_line_not_configured(client):
    from services.line_client import set_line_bot_client

    set_line_bot_client(None)
    r = await client.post(
        "/api/line/webhook",
        content=b"{}",
        headers={"X-Line-Signature": "abc"},
    )
    assert r.status_code == 503


async def test_webhook_returns_401_when_signature_missing(client, stub):
    r = await client.post("/api/line/webhook", content=b"{}")
    assert r.status_code == 401


async def test_webhook_returns_401_on_invalid_signature(client, stub):
    stub.raise_signature = True
    r = await client.post(
        "/api/line/webhook",
        content=b"{}",
        headers={"X-Line-Signature": "wrong"},
    )
    assert r.status_code == 401


async def test_webhook_returns_200_for_help(client, stub):
    stub.events_to_return = [_text_event("ヘルプ")]
    body = await _post_webhook(client)
    assert body == {"received": 1, "handled": 1}
    assert len(stub.replies) == 1
    assert "ヘルプ" in stub.replies[0]["text"] or "ヘルプ" in stub.replies[0]["text"]
    assert "おすすめ" in stub.replies[0]["text"]
    assert "分析" in stub.replies[0]["text"]


async def test_handler_exception_still_returns_200(client, stub, monkeypatch):
    from routes import line as line_route

    async def boom(ev, deps):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(line_route, "handle_event", boom)

    stub.events_to_return = [_text_event("ヘルプ")]
    body = await _post_webhook(client)
    assert body["received"] == 1
    assert body["handled"] == 0


# ---------------------------------------------------------------------------
# /help variants
# ---------------------------------------------------------------------------


async def test_help_alias_slash_help(client, stub):
    stub.events_to_return = [_text_event("/help")]
    await _post_webhook(client)
    assert "ヘルプ" in stub.replies[0]["text"] or "おすすめ" in stub.replies[0]["text"]


async def test_help_alias_question_mark(client, stub):
    stub.events_to_return = [_text_event("?")]
    await _post_webhook(client)
    assert "おすすめ" in stub.replies[0]["text"]


# ---------------------------------------------------------------------------
# Unknown command
# ---------------------------------------------------------------------------


async def test_unknown_command_shows_hint(client, stub):
    stub.events_to_return = [_text_event("わからない単語")]
    await _post_webhook(client)
    assert "認識できない" in stub.replies[0]["text"]


# ---------------------------------------------------------------------------
# おすすめ (funds recommend)
# ---------------------------------------------------------------------------


async def test_recommend_default_returns_flex_carousel(client, stub):
    df = _make_uptrend_df()
    mock = {"VOO": df, "VTI": df, "QQQ": df}

    with patch("agents.fund_screener._download_batch", return_value=mock):
        stub.events_to_return = [_text_event("おすすめ")]
        await _post_webhook(client)

    reply = stub.replies[0]
    assert reply["type"] == "flex"
    assert reply["contents"]["type"] == "carousel"
    assert len(reply["contents"]["contents"]) >= 1


async def test_recommend_us_alias_routes_to_us_index(client, stub):
    df = _make_uptrend_df()
    mock = {"VOO": df, "SPY": df, "VTI": df}

    with patch("agents.fund_screener._download_batch", return_value=mock):
        stub.events_to_return = [_text_event("おすすめ 米国")]
        await _post_webhook(client)

    reply = stub.replies[0]
    assert reply["type"] == "flex"


async def test_recommend_with_no_candidates_returns_text(client, stub):
    # ユニバースが空のカテゴリ
    with patch("agents.fund_screener._download_batch", return_value={}):
        stub.events_to_return = [_text_event("おすすめ 存在しないカテゴリ")]
        await _post_webhook(client)

    reply = stub.replies[0]
    assert reply["type"] == "text"
    assert "見つかりませんでした" in reply["text"] or "ヘルプ" in reply["text"]


async def test_recommend_flex_failure_falls_back_to_text(client, stub):
    df = _make_uptrend_df()
    mock = {"VOO": df}
    stub.fail_flex = True

    with patch("agents.fund_screener._download_batch", return_value=mock):
        stub.events_to_return = [_text_event("おすすめ 米国")]
        await _post_webhook(client)

    reply = stub.replies[0]
    assert reply["type"] == "text"
    assert "VOO" in reply["text"]
    assert "投資" in reply["text"] or "勧誘" in reply["text"]  # disclaimer


# ---------------------------------------------------------------------------
# スクリーニング (screener)
# ---------------------------------------------------------------------------


async def test_screen_default_returns_flex_carousel(client, stub):
    df = _make_screener_bullish_df()
    mock = {"7203.T": df, "6758.T": df}

    with patch("agents.screener._download_batch", return_value=mock):
        stub.events_to_return = [_text_event("スクリーニング")]
        await _post_webhook(client)

    reply = stub.replies[0]
    assert reply["type"] == "flex"
    assert reply["contents"]["type"] == "carousel"


async def test_screen_us_alias(client, stub):
    df = _make_screener_bullish_df()
    mock = {"AAPL": df}

    with patch("agents.screener._download_batch", return_value=mock):
        stub.events_to_return = [_text_event("スクリーニング US")]
        await _post_webhook(client)

    reply = stub.replies[0]
    # 候補無しなら text で返ってくる、ある場合は flex
    assert reply["type"] in ("flex", "text")


async def test_screen_no_candidates_returns_text(client, stub):
    with patch("agents.screener._download_batch", return_value={}):
        stub.events_to_return = [_text_event("スクリーニング JP")]
        await _post_webhook(client)

    reply = stub.replies[0]
    assert reply["type"] == "text"
    assert "ありません" in reply["text"] or "なし" in reply["text"]


# ---------------------------------------------------------------------------
# 分析 (analyze) — async with background push
# ---------------------------------------------------------------------------


async def test_analyze_without_args_shows_usage(client, stub):
    stub.events_to_return = [_text_event("分析")]
    await _post_webhook(client)
    assert "使い方" in stub.replies[0]["text"]


async def test_analyze_acks_immediately_then_pushes_result(client, stub):
    """分析コマンドは即 ack reply、バックグラウンド完了後に Push が来る。"""
    from services import line_handler

    async def fake_runner(req):
        # 実 Claude を叩かないモック実装
        await asyncio.sleep(0)
        return ("AAPL", "Apple Inc.", "本文サマリ — テクニカル / ファンダ評価")

    # handler が runner を選ぶのは deps.analyze_runner > _default_analyze_runner の順だが、
    # route 側で deps を組み立てているので _default_analyze_runner をパッチするのが手っ取り早い
    with patch.object(line_handler, "_default_analyze_runner", fake_runner):
        stub.events_to_return = [_text_event("分析 AAPL", user_id="U_a")]
        await _post_webhook(client)

    # ack 確認
    assert any("分析を開始しました" in r["text"] for r in stub.replies)

    # FastAPI BackgroundTasks はリクエスト完了後に走る。AsyncClient は context exit までに
    # それを待ってくれるため、ここでは pushes が既に来ているはず
    # 念のため 1 tick 余裕を入れる
    for _ in range(5):
        if stub.pushes:
            break
        await asyncio.sleep(0.05)

    assert stub.pushes, "background push should have fired"
    push = stub.pushes[0]
    assert push["to"] == "U_a"
    # Flex 成功時は flex、失敗時は text フォールバック
    assert push["type"] in ("flex", "text")
    body_text = push.get("text") or push.get("alt_text") or ""
    assert "AAPL" in body_text or "Apple" in body_text


async def test_analyze_runner_failure_pushes_error(client, stub):
    from services import line_handler

    async def boom_runner(req):
        raise RuntimeError("yfinance unavailable")

    with patch.object(line_handler, "_default_analyze_runner", boom_runner):
        stub.events_to_return = [_text_event("分析 AAPL", user_id="U_a")]
        await _post_webhook(client)

    for _ in range(5):
        if stub.pushes:
            break
        await asyncio.sleep(0.05)

    assert stub.pushes
    assert stub.pushes[0]["type"] == "text"
    assert "失敗" in stub.pushes[0]["text"]
    assert "yfinance" in stub.pushes[0]["text"]


# ---------------------------------------------------------------------------
# Flex JSON shape (unit)
# ---------------------------------------------------------------------------


async def test_flex_funds_carousel_caps_at_ten():
    from services.line_flex import funds_ranking_carousel

    cands = [
        {"rank": i, "ticker": f"F{i}", "name": f"Fund{i}", "score": 50, "rationale": ["a"]}
        for i in range(15)
    ]
    carousel = funds_ranking_carousel(cands)
    assert carousel["type"] == "carousel"
    assert len(carousel["contents"]) == 10


async def test_flex_funds_bubble_includes_button_to_analyze():
    from services.line_flex import funds_ranking_carousel

    carousel = funds_ranking_carousel([
        {"rank": 1, "ticker": "VOO", "name": "Vanguard", "score": 70, "rationale": ["強い"]}
    ])
    bubble = carousel["contents"][0]
    btn = bubble["footer"]["contents"][0]["action"]
    assert btn["type"] == "message"
    assert btn["text"] == "分析 VOO"


async def test_flex_screener_bubble_shape():
    from services.line_flex import screener_ranking_carousel

    carousel = screener_ranking_carousel([
        {"rank": 1, "ticker": "7203.T", "score": 60, "signals": ["RSI低"]}
    ])
    bubble = carousel["contents"][0]
    assert bubble["type"] == "bubble"
    assert "7203.T" in bubble["body"]["contents"][0]["text"]


async def test_flex_analysis_summary_truncates_long_body():
    from services.line_flex import analysis_summary_bubble

    bubble = analysis_summary_bubble(
        ticker="AAPL", company_name="Apple", body_text="x" * 5000
    )
    text = bubble["body"]["contents"][0]["text"]
    assert len(text) <= 1800
    assert text.endswith("…")


# ---------------------------------------------------------------------------
# Real SDK signature verification
# ---------------------------------------------------------------------------


async def test_real_sdk_parse_events_verifies_signature():
    from services.line_client import InvalidSignatureError, LineBotSdkClient

    secret = "testsecret"
    body = json.dumps({"events": []}).encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    good_sig = base64.b64encode(mac).decode("utf-8")

    line_client = LineBotSdkClient(
        channel_secret=secret, channel_access_token="dummy"
    )
    try:
        events = line_client.parse_events(body=body, signature=good_sig)
        assert events == []

        with pytest.raises(InvalidSignatureError):
            line_client.parse_events(body=body, signature="wrongsig")
    finally:
        await line_client.close()


# ---------------------------------------------------------------------------
# Default analyze runner aggregates report_complete event correctly (unit)
# ---------------------------------------------------------------------------


async def test_default_analyze_runner_aggregates_report_complete_event():
    from services import line_handler
    from models.stock import AnalysisRequest

    async def fake_run_analysis(req):
        yield {"type": "AssistantMessage", "data": "..."}
        yield {
            "type": "report_complete",
            "ticker": "7203.T",
            "company_name": "トヨタ",
            "report": {"report_text": "テクニカル: 強気\nファンダ: 良好"},
        }

    with patch.object(line_handler, "run_analysis", fake_run_analysis):
        ticker, name, body = await line_handler._default_analyze_runner(
            AnalysisRequest(query="トヨタ")
        )
    assert ticker == "7203.T"
    assert name == "トヨタ"
    assert "テクニカル" in body and "ファンダ" in body
