"""PROPOSAL-0011 P1: 分析結果の 3 点配信 / レート制限 / allow-list の unit テスト。

webhook 全体ではなく `line_handler` の内部関数を直接叩くことで、config の env reload
順序に依存せず検証する (settings 属性は monkeypatch.setattr で上書き)。
"""

from __future__ import annotations

import pytest

from services import line_handler
from services.access_control import reset_analyze_limiter
from services.blob_store import get_image_store, get_report_store, reset_blob_stores
from services.line_client import LineTextEvent

pytestmark = pytest.mark.asyncio


class _StubClient:
    def __init__(self) -> None:
        self.replies: list[dict] = []
        self.pushes: list[dict] = []

    async def reply_text(self, *, reply_token: str, text: str) -> None:
        self.replies.append({"type": "text", "text": text})

    async def reply_flex(self, *, reply_token, alt_text, contents) -> None:
        self.replies.append({"type": "flex", "alt_text": alt_text, "contents": contents})

    async def push_text(self, *, to: str, text: str) -> None:
        self.pushes.append({"type": "text", "to": to, "text": text})

    async def push_flex(self, *, to, alt_text, contents) -> None:
        self.pushes.append({"type": "flex", "to": to, "contents": contents})

    async def push_image(self, *, to, original_content_url, preview_image_url) -> None:
        self.pushes.append(
            {"type": "image", "to": to, "url": original_content_url}
        )

    async def close(self) -> None:  # pragma: no cover
        pass


def _deps(client):
    return line_handler.HandlerDeps(
        line_client=client, schedule_background=lambda f: None
    )


@pytest.fixture(autouse=True)
def _reset():
    reset_blob_stores()
    reset_analyze_limiter()
    yield
    reset_blob_stores()
    reset_analyze_limiter()


# ---------------------------------------------------------------------------
# 3 点配信
# ---------------------------------------------------------------------------


async def test_deliver_pushes_flex_and_image_with_urls(monkeypatch, tmp_path):
    monkeypatch.setattr(line_handler.settings, "public_base_url", "https://stock.example")

    chart = tmp_path / "chart.png"
    chart.write_bytes(b"\x89PNG fake bytes")

    client = _StubClient()
    result = line_handler.AnalyzeResult(
        ticker="7203.T",
        company_name="トヨタ",
        report_text="# トヨタ分析\n総合評価: 中立",
        chart_path=str(chart),
    )

    await line_handler._deliver_analysis(_deps(client), to="U_a", result=result)

    # (1) Flex 要約 + (2) チャート画像 の 2 push
    assert [p["type"] for p in client.pushes] == ["flex", "image"]

    flex = client.pushes[0]["contents"]
    # 全文ボタン 2 つ: [0]=HTML 閲覧 (primary), [1]=.md DL (secondary)
    buttons = flex["footer"]["contents"]
    assert len(buttons) == 2
    html_btn = buttons[0]["action"]
    md_btn = buttons[1]["action"]
    assert html_btn["type"] == "uri"
    assert html_btn["uri"].startswith("https://stock.example/api/line/report/")
    assert html_btn["uri"].endswith(".html")
    assert md_btn["uri"].endswith(".md")

    img_url = client.pushes[1]["url"]
    assert img_url.startswith("https://stock.example/api/line/image/")
    assert img_url.endswith(".png")

    # store に実体が入っている (HTML は変換済の text/html)
    html_id = html_btn["uri"].rsplit("/", 1)[-1][: -len(".html")]
    html_item = get_report_store().get(html_id)
    assert html_item is not None
    assert html_item[1].startswith("text/html")
    assert "トヨタ分析" in html_item[0].decode("utf-8")
    md_id = md_btn["uri"].rsplit("/", 1)[-1][: -len(".md")]
    md_item = get_report_store().get(md_id)
    assert md_item is not None and md_item[1].startswith("text/markdown")
    image_id = img_url.rsplit("/", 1)[-1][: -len(".png")]
    assert get_image_store().get(image_id) == (b"\x89PNG fake bytes", "image/png")


async def test_deliver_without_base_url_sends_only_flex(monkeypatch, tmp_path):
    monkeypatch.setattr(line_handler.settings, "public_base_url", "")

    chart = tmp_path / "chart.png"
    chart.write_bytes(b"png")

    client = _StubClient()
    result = line_handler.AnalyzeResult(
        ticker="AAPL", company_name="Apple", report_text="text", chart_path=str(chart)
    )
    await line_handler._deliver_analysis(_deps(client), to="U_a", result=result)

    # base_url 無し → 画像 push 無し、Flex のみ (全文ボタンも無し)
    assert [p["type"] for p in client.pushes] == ["flex"]
    assert "footer" not in client.pushes[0]["contents"]


async def test_deliver_missing_chart_skips_image(monkeypatch):
    monkeypatch.setattr(line_handler.settings, "public_base_url", "https://x.example")
    client = _StubClient()
    result = line_handler.AnalyzeResult(
        ticker="AAPL", company_name="Apple", report_text="text", chart_path=None
    )
    await line_handler._deliver_analysis(_deps(client), to="U_a", result=result)
    assert [p["type"] for p in client.pushes] == ["flex"]  # 全文ボタンは付くが画像無し
    assert "footer" in client.pushes[0]["contents"]


# ---------------------------------------------------------------------------
# レート制限
# ---------------------------------------------------------------------------


async def test_analyze_rate_limited_after_threshold(monkeypatch):
    monkeypatch.setattr(line_handler.settings, "analyze_rate_limit_per_day", 1)
    reset_analyze_limiter()

    scheduled: list = []
    deps = line_handler.HandlerDeps(
        line_client=_StubClient(), schedule_background=lambda f: scheduled.append(f)
    )
    ev = LineTextEvent(
        event_type="text", line_user_id="U_a", reply_token="rt", text="分析 トヨタ"
    )

    await line_handler._cmd_analyze(["トヨタ"], ev, deps)
    assert len(scheduled) == 1  # 1 回目は実行スケジュール

    client2 = _StubClient()
    deps2 = line_handler.HandlerDeps(
        line_client=client2, schedule_background=lambda f: scheduled.append(f)
    )
    await line_handler._cmd_analyze(["トヨタ"], ev, deps2)
    assert len(scheduled) == 1  # 2 回目はスケジュールされない
    assert any("上限" in r["text"] for r in client2.replies)


# ---------------------------------------------------------------------------
# allow-list
# ---------------------------------------------------------------------------


async def test_non_allowlisted_user_is_ignored(monkeypatch):
    monkeypatch.setattr(line_handler.settings, "family_user_ids", "U_ok")
    client = _StubClient()
    ev = LineTextEvent(
        event_type="text", line_user_id="U_eve", reply_token="rt", text="ヘルプ"
    )
    await line_handler._handle_text(ev, _deps(client))
    assert client.replies == []  # 黙殺


async def test_allowlisted_user_gets_help(monkeypatch):
    monkeypatch.setattr(line_handler.settings, "family_user_ids", "U_ok")
    client = _StubClient()
    ev = LineTextEvent(
        event_type="text", line_user_id="U_ok", reply_token="rt", text="ヘルプ"
    )
    await line_handler._handle_text(ev, _deps(client))
    assert any("ヘルプ" in r["text"] for r in client.replies)


# ---------------------------------------------------------------------------
# Cloud Tasks 委譲 (P3-A)
# ---------------------------------------------------------------------------


async def test_analyze_enqueues_when_tasks_enabled(monkeypatch):
    monkeypatch.setattr(line_handler.settings, "tasks_enabled", True)
    enqueued = []
    monkeypatch.setattr(
        line_handler, "enqueue_analysis", lambda uid, target: enqueued.append((uid, target))
    )
    scheduled = []
    client = _StubClient()
    deps = line_handler.HandlerDeps(
        line_client=client, schedule_background=lambda f: scheduled.append(f)
    )
    ev = LineTextEvent(
        event_type="text", line_user_id="U_a", reply_token="rt", text="分析 トヨタ"
    )
    await line_handler._cmd_analyze(["トヨタ"], ev, deps)

    assert enqueued == [("U_a", "トヨタ")]
    assert scheduled == []  # in-process 実行はしない
    assert any("分析を開始" in r["text"] for r in client.replies)  # ack は返す


async def test_analyze_falls_back_inline_when_enqueue_fails(monkeypatch):
    monkeypatch.setattr(line_handler.settings, "tasks_enabled", True)

    def boom(uid, target):
        raise RuntimeError("tasks unavailable")

    monkeypatch.setattr(line_handler, "enqueue_analysis", boom)
    scheduled = []
    client = _StubClient()
    deps = line_handler.HandlerDeps(
        line_client=client, schedule_background=lambda f: scheduled.append(f)
    )
    ev = LineTextEvent(
        event_type="text", line_user_id="U_a", reply_token="rt", text="分析 トヨタ"
    )
    await line_handler._cmd_analyze(["トヨタ"], ev, deps)

    assert len(scheduled) == 1  # enqueue 失敗 → in-process にフォールバック
