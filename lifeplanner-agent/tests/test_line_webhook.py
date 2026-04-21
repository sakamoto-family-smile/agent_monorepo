"""LINE Bot Webhook (/api/line/webhook) と `line_handler` の統合テスト。

方針:
  - LINE SDK を叩かずに済むよう `StubLineBotClient` を `set_line_bot_client` で差し込む
  - イベントはスタブの `events_to_return` に事前セットして webhook POST で再生する
  - DB 影響は後続の webhook 呼び出し (`/whoami` 等) で確認する
  - LLM は `client` fixture 内で `LLM_MOCK_MODE=true` にされているため外部呼出は発生しない
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from services.line_client import (
    InvalidSignatureError,
    LineEvent,
    LineFileEvent,
    LineTextEvent,
    set_line_bot_client,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Stub LINE client
# ---------------------------------------------------------------------------


class StubLineBotClient:
    """テスト用スタブ。parse_events の返却値とファイル内容を事前に仕込める。

    `reply_text` と `reply_flex` の両方を記録する。
    `replies[i]["text"]` は text 応答なら本文、flex 応答なら alt_text を格納する。
    これにより "text に <文字列> が含まれる" 系の既存アサートが
    Flex 化後も (alt_text を通じて) そのまま通る。
    """

    def __init__(self) -> None:
        self.events_to_return: list[LineEvent] = []
        self.file_content: bytes = b""
        self.raise_signature: bool = False
        self.replies: list[dict] = []
        self.close_called: bool = False
        # Flex 呼出時に意図的に失敗させるフラグ (フォールバックテスト用)
        self.fail_flex: bool = False

    def parse_events(self, *, body: bytes, signature: str):
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

    async def get_message_content(self, *, message_id: str) -> bytes:
        return self.file_content

    async def close(self) -> None:
        self.close_called = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stub(client):
    s = StubLineBotClient()
    set_line_bot_client(s)
    yield s
    set_line_bot_client(None)


def _text_event(text: str, *, user_id: str = "U_alice", reply_token: str = "rt") -> LineTextEvent:
    return LineTextEvent(
        event_type="text", line_user_id=user_id, reply_token=reply_token, text=text
    )


def _file_event(
    *,
    message_id: str = "m1",
    file_name: str = "mf.csv",
    file_size: int = 100,
    user_id: str = "U_alice",
    reply_token: str = "rt",
) -> LineFileEvent:
    return LineFileEvent(
        event_type="file",
        line_user_id=user_id,
        reply_token=reply_token,
        message_id=message_id,
        file_name=file_name,
        file_size=file_size,
    )


async def _post_webhook(client, body: bytes = b'{"events":[]}') -> dict:
    r = await client.post(
        "/api/line/webhook",
        content=body,
        headers={"X-Line-Signature": "stub", "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Route-level: 503 / 401
# ---------------------------------------------------------------------------


async def test_webhook_returns_503_when_line_not_configured(client):
    # fixture `stub` を使わず、LINE client 未設定のまま叩く
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


async def test_webhook_returns_200_and_counts_events(client, stub):
    stub.events_to_return = [_text_event("/help")]
    body = await _post_webhook(client)
    assert body == {"received": 1, "handled": 1}
    assert len(stub.replies) == 1
    assert "help" in stub.replies[0]["text"].lower() or "/help" in stub.replies[0]["text"]


async def test_handler_exception_still_returns_200(client, stub, monkeypatch):
    """ハンドラ内部で例外が起きても LINE には 200 を返す。"""
    # routes.line は `from services.line_handler import handle_event` で
    # 名前を取り込んでいるため、その再束縛を差し替える。
    from routes import line as line_route

    async def boom(ev, deps):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(line_route, "handle_event", boom)

    stub.events_to_return = [_text_event("/help")]
    body = await _post_webhook(client)
    assert body["received"] == 1
    assert body["handled"] == 0


# ---------------------------------------------------------------------------
# 自動連携: 未連携ユーザーが自然文を送ると世帯が自動作成される
# ---------------------------------------------------------------------------


async def test_first_text_from_new_user_auto_creates_household(client, stub):
    stub.events_to_return = [_text_event("こんにちは")]
    await _post_webhook(client)

    assert len(stub.replies) == 1
    reply = stub.replies[0]["text"]
    assert "はじめまして" in reply
    assert "世帯ID:" in reply
    # 自動生成 ID は `line-` prefix
    assert "line-" in reply


async def test_whoami_after_auto_link_shows_household(client, stub):
    stub.events_to_return = [_text_event("こんにちは")]
    await _post_webhook(client)
    stub.replies.clear()

    stub.events_to_return = [_text_event("/whoami")]
    await _post_webhook(client)

    reply = stub.replies[0]["text"]
    assert "LINE userId=U_alice" in reply
    assert "世帯ID=line-" in reply


# ---------------------------------------------------------------------------
# /help はいつでも動く
# ---------------------------------------------------------------------------


async def test_help_works_without_link(client, stub):
    stub.events_to_return = [_text_event("/help", user_id="U_new")]
    await _post_webhook(client)
    assert "/help" in stub.replies[0]["text"]
    assert "/link" in stub.replies[0]["text"]


# ---------------------------------------------------------------------------
# /link
# ---------------------------------------------------------------------------


async def test_link_to_existing_household_succeeds(client, stub):
    # 世帯 test-household は `client` fixture の DEV_HOUSEHOLD_ID、まだ households テーブルに
    # 入っていないので API 経由で作成する。/api/scenarios を呼ぶと ensure_household が走る
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
    assert r.status_code == 201

    stub.events_to_return = [_text_event("/link test-household", user_id="U_bob")]
    await _post_webhook(client)

    assert "参加しました" in stub.replies[0]["text"]

    # /whoami で確認
    stub.replies.clear()
    stub.events_to_return = [_text_event("/whoami", user_id="U_bob")]
    await _post_webhook(client)
    assert "世帯ID=test-household" in stub.replies[0]["text"]


async def test_link_to_missing_household_rejected(client, stub):
    stub.events_to_return = [_text_event("/link unknown-household-xyz", user_id="U_c")]
    await _post_webhook(client)
    assert "見つかりませんでした" in stub.replies[0]["text"]


async def test_link_when_already_linked_is_rejected(client, stub):
    # 自動連携させる
    stub.events_to_return = [_text_event("hi", user_id="U_d")]
    await _post_webhook(client)
    stub.replies.clear()

    stub.events_to_return = [_text_event("/link test-household", user_id="U_d")]
    await _post_webhook(client)
    assert "既に世帯" in stub.replies[0]["text"]
    assert "/unlink" in stub.replies[0]["text"]


async def test_link_requires_one_argument(client, stub):
    stub.events_to_return = [_text_event("/link", user_id="U_e")]
    await _post_webhook(client)
    assert "使い方" in stub.replies[0]["text"]


# ---------------------------------------------------------------------------
# /invite / /unlink
# ---------------------------------------------------------------------------


async def test_invite_shows_link_command_with_household_id(client, stub):
    # 自動連携
    stub.events_to_return = [_text_event("hi", user_id="U_f")]
    await _post_webhook(client)
    stub.replies.clear()

    stub.events_to_return = [_text_event("/invite", user_id="U_f")]
    await _post_webhook(client)

    reply = stub.replies[0]["text"]
    assert reply.count("/link ") == 1
    assert "line-" in reply  # 自動生成 household_id


async def test_unlink_removes_link(client, stub):
    stub.events_to_return = [_text_event("hi", user_id="U_g")]
    await _post_webhook(client)
    stub.replies.clear()

    stub.events_to_return = [_text_event("/unlink", user_id="U_g")]
    await _post_webhook(client)
    assert "連携を解除しました" in stub.replies[0]["text"]

    # /whoami は連携必須なので hint が返る
    stub.replies.clear()
    stub.events_to_return = [_text_event("/whoami", user_id="U_g")]
    await _post_webhook(client)
    assert "連携されていません" in stub.replies[0]["text"]


# ---------------------------------------------------------------------------
# /scenarios / /summarize / /compare
# ---------------------------------------------------------------------------


async def _create_linked_user_with_scenarios(client, stub, *, n: int = 2) -> list[int]:
    """test-household にシナリオを n 件作成し、U_sc を /link する。シナリオ ID のリストを返す。"""
    ids: list[int] = []
    for i in range(n):
        r = await client.post(
            "/api/scenarios",
            json={
                "name": f"S{i}",
                "description": "",
                "primary_salary": "6000000",
                "start_year": 2026,
                "horizon_years": 30,
            },
        )
        assert r.status_code == 201
        ids.append(r.json()["id"])

    stub.events_to_return = [_text_event("/link test-household", user_id="U_sc")]
    await _post_webhook(client)
    stub.replies.clear()
    return ids


async def test_scenarios_empty_when_household_has_none(client, stub):
    stub.events_to_return = [_text_event("hi", user_id="U_sc")]
    await _post_webhook(client)
    stub.replies.clear()

    stub.events_to_return = [_text_event("/scenarios", user_id="U_sc")]
    await _post_webhook(client)
    assert "シナリオがまだ" in stub.replies[0]["text"]


async def test_scenarios_lists_ids_and_names(client, stub):
    ids = await _create_linked_user_with_scenarios(client, stub, n=2)

    stub.events_to_return = [_text_event("/scenarios", user_id="U_sc")]
    await _post_webhook(client)
    reply = stub.replies[0]["text"]
    assert f"{ids[0]}: S0" in reply
    assert f"{ids[1]}: S1" in reply


async def test_summarize_invokes_llm_and_replies_narrative(client, stub):
    ids = await _create_linked_user_with_scenarios(client, stub, n=1)

    stub.events_to_return = [_text_event(f"/summarize {ids[0]}", user_id="U_sc")]
    await _post_webhook(client)
    reply = stub.replies[0]["text"]
    # MockLLMClient は「【モック要約】」を含む文字列を返す
    assert "モック要約" in reply


async def test_summarize_rejects_non_numeric(client, stub):
    await _create_linked_user_with_scenarios(client, stub, n=1)
    stub.events_to_return = [_text_event("/summarize abc", user_id="U_sc")]
    await _post_webhook(client)
    assert "使い方" in stub.replies[0]["text"]


async def test_summarize_missing_scenario_returns_error(client, stub):
    await _create_linked_user_with_scenarios(client, stub, n=1)
    stub.events_to_return = [_text_event("/summarize 99999", user_id="U_sc")]
    await _post_webhook(client)
    assert "エラー" in stub.replies[0]["text"]


async def test_compare_requires_at_least_two_ids(client, stub):
    await _create_linked_user_with_scenarios(client, stub, n=2)
    stub.events_to_return = [_text_event("/compare 1", user_id="U_sc")]
    await _post_webhook(client)
    assert "使い方" in stub.replies[0]["text"]


async def test_compare_two_scenarios_returns_narrative(client, stub):
    ids = await _create_linked_user_with_scenarios(client, stub, n=2)
    stub.events_to_return = [
        _text_event(f"/compare {ids[0]} {ids[1]}", user_id="U_sc")
    ]
    await _post_webhook(client)
    assert "モック要約" in stub.replies[0]["text"]


# ---------------------------------------------------------------------------
# 未知コマンド / プレーンテキスト
# ---------------------------------------------------------------------------


async def test_unknown_slash_command_when_linked_shows_hint(client, stub):
    stub.events_to_return = [_text_event("hi", user_id="U_x")]
    await _post_webhook(client)
    stub.replies.clear()

    stub.events_to_return = [_text_event("/foo bar", user_id="U_x")]
    await _post_webhook(client)
    assert "認識できない" in stub.replies[0]["text"]


async def test_plain_text_when_linked_shows_hint(client, stub):
    stub.events_to_return = [_text_event("hi", user_id="U_y")]
    await _post_webhook(client)
    stub.replies.clear()

    stub.events_to_return = [_text_event("adhoc talk", user_id="U_y")]
    await _post_webhook(client)
    assert "認識できない" in stub.replies[0]["text"]


# ---------------------------------------------------------------------------
# File (CSV) 取込
# ---------------------------------------------------------------------------


async def test_file_rejected_when_not_linked(client, stub):
    stub.events_to_return = [_file_event(user_id="U_nl")]
    await _post_webhook(client)
    assert "世帯連携が必要" in stub.replies[0]["text"]


async def test_file_too_large_rejected(client, stub):
    # 自動連携
    stub.events_to_return = [_text_event("hi", user_id="U_big")]
    await _post_webhook(client)
    stub.replies.clear()

    stub.events_to_return = [_file_event(user_id="U_big", file_size=10 * 1024 * 1024)]
    await _post_webhook(client)
    assert "大きすぎます" in stub.replies[0]["text"]


async def test_file_with_invalid_csv_returns_error(client, stub):
    stub.events_to_return = [_text_event("hi", user_id="U_bad")]
    await _post_webhook(client)
    stub.replies.clear()

    stub.file_content = b"not a valid csv, missing columns"
    stub.events_to_return = [_file_event(user_id="U_bad", file_size=30)]
    await _post_webhook(client)
    assert "CSV の解析に失敗" in stub.replies[0]["text"]


async def test_file_with_valid_csv_imports_transactions(client, stub):
    from tests.fixtures.build_sample_csv import build_csv

    # 事前に test-household にリンクさせる (auto-link で生成 ID を使うよりテスト可読性が高い)
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
    assert r.status_code == 201

    stub.events_to_return = [_text_event("/link test-household", user_id="U_csv")]
    await _post_webhook(client)
    stub.replies.clear()

    csv_bytes = build_csv()
    stub.file_content = csv_bytes
    stub.events_to_return = [_file_event(user_id="U_csv", file_size=len(csv_bytes))]
    await _post_webhook(client)

    reply = stub.replies[0]["text"]
    assert "CSV 取り込み完了" in reply
    assert "読み込み 3 件" in reply
    assert "追加 3 件" in reply

    # /api/transactions で確認 (レスポンスは envelope 形式)
    r = await client.get(
        "/api/transactions",
        headers={"X-Household-ID": "test-household"},
        params={"start": "2026-04-01", "end": "2026-04-30"},
    )
    assert r.status_code == 200
    assert len(r.json()["items"]) == 3


# ---------------------------------------------------------------------------
# Real SDK: 署名検証が HMAC-SHA256 ベースで動く (統合確認)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Flex Message: /scenarios, /summarize, /compare
# ---------------------------------------------------------------------------


async def test_scenarios_sends_flex_carousel(client, stub):
    ids = await _create_linked_user_with_scenarios(client, stub, n=2)

    stub.events_to_return = [_text_event("/scenarios", user_id="U_sc")]
    await _post_webhook(client)

    reply = stub.replies[0]
    assert reply["type"] == "flex"
    contents = reply["contents"]
    assert contents["type"] == "carousel"
    assert len(contents["contents"]) == 2
    bubble_ids = [
        bubble["body"]["contents"][0]["text"] for bubble in contents["contents"]
    ]
    assert bubble_ids == [f"#{ids[0]}", f"#{ids[1]}"]
    # 各 bubble に /summarize ボタンが入る
    for bubble in contents["contents"]:
        action = bubble["footer"]["contents"][0]["action"]
        assert action["type"] == "message"
        assert action["text"].startswith("/summarize ")


async def test_summarize_sends_flex_bubble_with_title(client, stub):
    ids = await _create_linked_user_with_scenarios(client, stub, n=1)

    stub.events_to_return = [_text_event(f"/summarize {ids[0]}", user_id="U_sc")]
    await _post_webhook(client)

    reply = stub.replies[0]
    assert reply["type"] == "flex"
    contents = reply["contents"]
    assert contents["type"] == "bubble"
    title = contents["header"]["contents"][0]["text"]
    assert "S0 の要約" in title
    body_text = contents["body"]["contents"][0]["text"]
    assert "モック要約" in body_text


async def test_compare_sends_flex_bubble_with_comparison_title(client, stub):
    ids = await _create_linked_user_with_scenarios(client, stub, n=2)

    stub.events_to_return = [
        _text_event(f"/compare {ids[0]} {ids[1]}", user_id="U_sc")
    ]
    await _post_webhook(client)

    reply = stub.replies[0]
    assert reply["type"] == "flex"
    title = reply["contents"]["header"]["contents"][0]["text"]
    assert "比較:" in title
    assert "S0" in title and "S1" in title


async def test_flex_failure_falls_back_to_text(client, stub):
    """reply_flex が例外を吐いたら reply_text にフォールバックする。"""
    ids = await _create_linked_user_with_scenarios(client, stub, n=2)
    stub.fail_flex = True

    stub.events_to_return = [_text_event("/scenarios", user_id="U_sc")]
    await _post_webhook(client)
    reply = stub.replies[0]
    assert reply["type"] == "text"
    assert f"{ids[0]}: S0" in reply["text"]


# ---------------------------------------------------------------------------
# Flex JSON structure (unit)
# ---------------------------------------------------------------------------


async def test_flex_narrative_bubble_truncates_long_body():
    from services.line_flex import narrative_bubble

    body = "x" * 5000
    bubble = narrative_bubble(title="title", body_text=body)
    text = bubble["body"]["contents"][0]["text"]
    assert len(text) <= 1800
    assert text.endswith("…")


async def test_flex_scenarios_carousel_caps_at_ten():
    from services.line_flex import scenarios_carousel

    scenarios = [(i, f"S{i}", None) for i in range(15)]
    carousel = scenarios_carousel(scenarios)
    assert len(carousel["contents"]) == 10


async def test_flex_scenario_bubble_includes_description_when_present():
    from services.line_flex import scenarios_carousel

    carousel = scenarios_carousel([(1, "Base", "家族プランA"), (2, "Alt", None)])
    first_body = carousel["contents"][0]["body"]["contents"]
    texts = [c["text"] for c in first_body]
    assert "家族プランA" in texts
    second_body = carousel["contents"][1]["body"]["contents"]
    # description 無しなら 2 行のみ
    assert len(second_body) == 2


# ---------------------------------------------------------------------------
# Real SDK
# ---------------------------------------------------------------------------


async def test_real_sdk_parse_events_verifies_signature():
    """LineBotSdkClient.parse_events が正しい署名を通し、誤った署名を弾くことを確認。

    SDK の AsyncApiClient は生成時に asyncio 実行ループを必要とするため async で走らせる。
    ネットワークは叩かない。
    """
    from services.line_client import LineBotSdkClient

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
