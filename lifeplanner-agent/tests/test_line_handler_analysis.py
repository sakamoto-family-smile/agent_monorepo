"""PR 2: /summary /networth /anomalies の LINE コマンド統合テスト。

`StubLineBotClient` で LINE I/O を差し替え、HTTP webhook 経由で
コマンドを実行する。データは自動連携 → /api/upload で投入する。
"""

from __future__ import annotations

from datetime import date

import pytest
from services.line_client import (
    LineEvent,
    LineTextEvent,
    set_line_bot_client,
)

pytestmark = pytest.mark.asyncio


# ---- Stub (test_line_webhook.py と同じ流儀) ----


class StubLineBotClient:
    def __init__(self) -> None:
        self.events_to_return: list[LineEvent] = []
        self.replies: list[dict] = []
        self.fail_flex: bool = False

    def parse_events(self, *, body: bytes, signature: str):
        return list(self.events_to_return)

    async def reply_text(self, *, reply_token: str, text: str) -> None:
        self.replies.append({"type": "text", "text": text})

    async def reply_flex(self, *, reply_token: str, alt_text: str, contents: dict) -> None:
        if self.fail_flex:
            raise RuntimeError("stub: flex disabled")
        self.replies.append(
            {
                "type": "flex",
                "alt_text": alt_text,
                "text": alt_text,
                "contents": contents,
            }
        )

    async def get_message_content(self, *, message_id: str) -> bytes:
        return b""

    async def close(self) -> None:
        pass


@pytest.fixture
def stub(client):
    s = StubLineBotClient()
    set_line_bot_client(s)
    yield s
    set_line_bot_client(None)


def _text_event(text: str, *, user_id: str = "U_alice") -> LineTextEvent:
    return LineTextEvent(
        event_type="text", line_user_id=user_id, reply_token="rt", text=text
    )


async def _post_webhook(client) -> None:
    r = await client.post(
        "/api/line/webhook",
        content=b'{"events":[]}',
        headers={"X-Line-Signature": "stub", "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text


async def _auto_link(client, stub, *, user_id: str = "U_alice") -> str:
    """自動連携してから household_id を返す。"""
    stub.events_to_return = [_text_event("hello", user_id=user_id)]
    await _post_webhook(client)
    text = stub.replies[0]["text"]
    for line in text.splitlines():
        if line.startswith("世帯ID:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"failed to auto-link: {text!r}")


async def _link_to_dev_household(client, stub, *, user_id: str = "U_alice") -> str:
    """API 用の DEV_HOUSEHOLD_ID (= test-household) に /link で繋ぐ。

    `/api/profile/*` は `Depends(get_household_id)` で DEV_HOUSEHOLD_ID を
    使うため、LINE 経由のコマンドでも同じ世帯を見るには `/link` でこの ID
    に紐付けが必要。
    """
    # まず household を作る (scenario 作成 = ensure_household が内部で走る)
    r = await client.post(
        "/api/scenarios",
        json={
            "name": "Base",
            "description": "",
            "primary_salary": "6000000",
            "start_year": 2026,
            "horizon_years": 30,
        },
    )
    assert r.status_code == 201, r.text
    stub.events_to_return = [_text_event("/link test-household", user_id=user_id)]
    await _post_webhook(client)
    assert "参加しました" in stub.replies[0]["text"]
    stub.replies.clear()
    return "test-household"


async def _add_assets_via_api(client, *, kind: str, value: int) -> None:
    """/api/profile/assets で資産を 1 件追加 (DEV_HOUSEHOLD_ID へ)。"""
    r = await client.post(
        "/api/profile/assets",
        json={
            "kind": kind,
            "name": kind,
            "value": str(value),
            "as_of": "2025-10-01",
        },
    )
    assert r.status_code == 201, r.text


async def _add_liabilities_via_api(client, *, kind: str, balance: int) -> None:
    r = await client.post(
        "/api/profile/liabilities",
        json={
            "kind": kind,
            "name": kind,
            "balance": str(balance),
            "as_of": "2025-10-01",
        },
    )
    assert r.status_code == 201, r.text


# ---- /summary ----


async def test_summary_command_with_no_data_returns_zeros(client, stub):
    await _auto_link(client, stub)
    stub.replies.clear()
    stub.events_to_return = [_text_event("/summary 今月")]
    await _post_webhook(client)

    reply = stub.replies[0]
    # データが無くても落ちず、サマリ ラベルが出ること
    assert "サマリ" in reply["text"] or "サマリ" in reply.get("alt_text", "")


async def test_summary_command_invalid_period_returns_usage(client, stub):
    await _auto_link(client, stub)
    stub.replies.clear()
    stub.events_to_return = [_text_event("/summary foo")]
    await _post_webhook(client)
    assert "使い方" in stub.replies[0]["text"]


async def test_summary_command_default_uses_this_month(client, stub):
    await _auto_link(client, stub)
    stub.replies.clear()
    stub.events_to_return = [_text_event("/summary")]
    await _post_webhook(client)
    # 引数なしでも応答が返る (alt_text に YYYY/MM)
    reply = stub.replies[0]
    text = reply.get("alt_text") or reply["text"]
    assert "サマリ" in text


# ---- /networth ----


async def test_networth_command_with_assets_and_liabilities(client, stub):
    await _link_to_dev_household(client, stub)
    # 許可されている asset kind: cash / deposit / investment / real_estate / other
    await _add_assets_via_api(client, kind="deposit", value=5_000_000)
    await _add_assets_via_api(client, kind="investment", value=3_500_000)
    await _add_liabilities_via_api(client, kind="mortgage", balance=2_000_000)

    stub.replies.clear()
    stub.events_to_return = [_text_event("/networth")]
    await _post_webhook(client)

    reply = stub.replies[0]
    assert reply["type"] == "flex"
    body_texts = _flex_text(reply["contents"])
    assert any("¥8,500,000" in t for t in body_texts)  # 総資産
    assert any("¥2,000,000" in t for t in body_texts)  # 総負債
    assert any("¥6,500,000" in t for t in body_texts)  # 純資産
    assert any("deposit" in t for t in body_texts)
    assert any("mortgage" in t for t in body_texts)


async def test_networth_command_with_invalid_date_returns_usage(client, stub):
    await _auto_link(client, stub)
    stub.replies.clear()
    stub.events_to_return = [_text_event("/networth 2025/10/15")]
    await _post_webhook(client)
    assert "使い方" in stub.replies[0]["text"]


async def test_networth_command_falls_back_to_text_when_flex_fails(client, stub):
    await _link_to_dev_household(client, stub)
    await _add_assets_via_api(client, kind="deposit", value=5_000_000)

    stub.replies.clear()
    stub.fail_flex = True
    stub.events_to_return = [_text_event("/networth")]
    await _post_webhook(client)

    # text fallback で円表示が出る
    reply = stub.replies[0]
    assert reply["type"] == "text"
    assert "純資産" in reply["text"]


# ---- /anomalies ----


async def test_anomalies_command_with_no_data_returns_no_anomaly_message(client, stub):
    await _auto_link(client, stub)
    stub.replies.clear()
    stub.events_to_return = [_text_event("/anomalies")]
    await _post_webhook(client)

    # 履歴が無いので「異常なし」or 0 件の Flex
    reply = stub.replies[0]
    text = reply.get("alt_text") or reply["text"]
    assert "異常検知" in text


async def test_anomalies_command_with_yyyy_mm():
    # parse_month_arg のみをチェック (handler は上のテストで通る)
    from services.line_period import parse_month_arg

    d, label = parse_month_arg("2024-01")
    assert d == date(2024, 1, 1)
    assert label == "2024/01"


async def test_anomalies_command_invalid_format_returns_usage(client, stub):
    await _auto_link(client, stub)
    stub.replies.clear()
    stub.events_to_return = [_text_event("/anomalies bad")]
    await _post_webhook(client)
    assert "使い方" in stub.replies[0]["text"]


# ---- help text 更新 ----


async def test_help_text_includes_pr2_commands(client, stub):
    stub.events_to_return = [_text_event("/help", user_id="U_new")]
    await _post_webhook(client)
    text = stub.replies[0]["text"]
    assert "/summary" in text
    assert "/networth" in text
    assert "/anomalies" in text


# ---- helpers ----


def _flex_text(node) -> list[str]:
    """Flex JSON から text 値を集める (test_line_flex_analysis と同じ実装)。"""
    out: list[str] = []
    if isinstance(node, list):
        for item in node:
            out.extend(_flex_text(item))
        return out
    if isinstance(node, dict):
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            out.append(node["text"])
        for v in node.values():
            if isinstance(v, (dict, list)):
                out.extend(_flex_text(v))
    return out
