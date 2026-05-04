"""Phase 3-B: Consultation の tool_use loop と analytics emit のテスト。

LLM client は MockLLMClient で振り合せて Vertex API を呼ばずに動作確認する。
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest
from repositories.event_repo import EventRepo
from repositories.session_repo import (
    GAP_ASKED_CLARIFICATION,
    GAP_COMPLETED,
    SessionRepo,
)
from services.consultation import (
    Consultation,
    LLMResponse,
    ToolCall,
)


class _MockLLM:
    """generate() 呼び出しで予約された LLMResponse を順番に返す mock。"""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._queue = list(responses)
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if not self._queue:
            raise RuntimeError("MockLLM out of responses")
        return self._queue.pop(0)


class _MockAnalyticsLogger:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, **kwargs):
        self.events.append(kwargs)


@pytest.fixture
async def setup():
    """EventRepo + SessionRepo + AnalyticsLogger mock。"""
    with tempfile.TemporaryDirectory() as td:
        db = pathlib.Path(td) / "test.db"
        ev = EventRepo(database_url=f"sqlite+aiosqlite:///{db}")
        await ev.initialize()
        sr = SessionRepo(engine=ev.engine)
        al = _MockAnalyticsLogger()
        yield ev, sr, al
        await ev.dispose()


def _setup_vertex(monkeypatch: pytest.MonkeyPatch) -> None:
    """vertex_configured を True にする env を仕込む (importlib reload で settings を取り直す)。"""
    from importlib import reload

    monkeypatch.setenv("VERTEX_PROJECT", "test-project")
    monkeypatch.setenv("VERTEX_LOCATION", "asia-northeast1")
    monkeypatch.setenv("VERTEX_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("VERTEX_MAX_TOOL_ITERATIONS", "5")
    monkeypatch.setenv("VERTEX_HISTORY_WINDOW", "20")
    import config

    reload(config)
    import services.consultation as consultation_mod

    reload(consultation_mod)


@pytest.mark.asyncio
async def test_respond_simple_text(setup, monkeypatch: pytest.MonkeyPatch) -> None:
    """tool 不要で text 応答するケース。"""
    _setup_vertex(monkeypatch)
    ev, sr, al = setup
    llm = _MockLLM([LLMResponse(text="こんにちは!")])

    from services.consultation import Consultation

    c = Consultation(
        repo=ev,
        session_repo=sr,
        analytics_logger=al,
        family_id="f1",
        line_user_id="U1",
        llm_client=llm,
    )
    reply = await c.respond("こんにちは")
    assert reply == "こんにちは!"

    # 履歴に user + assistant の 2 件保存されている
    sess = await sr.get_session(line_user_id="U1")
    assert sess is not None
    history = await sr.fetch_history(conversation_id=sess.current_conversation_id)
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[1].role == "assistant"
    assert history[1].capability_gap == GAP_COMPLETED

    # analytics: started + 2 message_emitted
    actions = [e["fields"]["action"] for e in al.events]
    assert "consultation_started" in actions
    assert actions.count("consultation_message_emitted") == 2


@pytest.mark.asyncio
async def test_respond_with_query_events_tool(setup, monkeypatch: pytest.MonkeyPatch) -> None:
    """tool 1 回 → 結果ベースで text 応答するケース。"""
    _setup_vertex(monkeypatch)
    ev, sr, al = setup
    llm = _MockLLM(
        [
            # 1 回目: query_events 呼び出し
            LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        "query_events",
                        {
                            "date_from": "2026-02-01",
                            "date_to": "2026-02-28",
                            "event_types": ["formula"],
                            "aggregation": "sum_volume_ml",
                        },
                    )
                ],
            ),
            # 2 回目: text 応答
            LLMResponse(text="2 月のミルク量は 0 ml でした (記録なし)。"),
        ]
    )

    c = Consultation(
        repo=ev,
        session_repo=sr,
        analytics_logger=al,
        family_id="f1",
        line_user_id="U1",
        llm_client=llm,
    )
    reply = await c.respond("2 月のミルク量を教えて")
    assert "2 月" in reply

    # tool_use と tool_result が履歴に残る
    sess = await sr.get_session(line_user_id="U1")
    history = await sr.fetch_history(conversation_id=sess.current_conversation_id)
    roles = [m.role for m in history]
    assert "tool_use" in roles
    assert "tool_result" in roles
    # tool_use メッセージに tool_name が記録される
    tool_use_msg = next(m for m in history if m.role == "tool_use")
    assert tool_use_msg.tool_name == "query_events"


@pytest.mark.asyncio
async def test_respond_with_ask_clarification(setup, monkeypatch: pytest.MonkeyPatch) -> None:
    """ask_clarification を呼ぶと早期 return + capability_gap=asked_clarification。"""
    _setup_vertex(monkeypatch)
    ev, sr, al = setup
    llm = _MockLLM(
        [
            LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        "ask_clarification",
                        {"question": "回数 (回) を聞きたいですか? 量 (ml) ですか?"},
                    )
                ],
            ),
        ]
    )

    c = Consultation(
        repo=ev,
        session_repo=sr,
        analytics_logger=al,
        family_id="f1",
        line_user_id="U1",
        llm_client=llm,
    )
    reply = await c.respond("ミルクは?")
    assert "回数" in reply or "ml" in reply

    sess = await sr.get_session(line_user_id="U1")
    history = await sr.fetch_history(conversation_id=sess.current_conversation_id)
    last_assistant = [m for m in history if m.role == "assistant"][-1]
    assert last_assistant.capability_gap == GAP_ASKED_CLARIFICATION


@pytest.mark.asyncio
async def test_respond_returns_not_configured_when_vertex_missing(
    setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VERTEX_PROJECT 未設定なら CONSULT_NOT_CONFIGURED を返す。"""
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    from importlib import reload

    import config

    reload(config)
    import services.consultation as consultation_mod

    reload(consultation_mod)
    from services.consultation import CONSULT_NOT_CONFIGURED, Consultation

    ev, sr, al = setup
    c = Consultation(
        repo=ev,
        session_repo=sr,
        analytics_logger=al,
        family_id="f1",
        line_user_id="U1",
        llm_client=_MockLLM([]),
    )
    reply = await c.respond("こんにちは")
    assert reply == CONSULT_NOT_CONFIGURED


@pytest.mark.asyncio
async def test_analytics_emission_does_not_leak_content(
    setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """analytics-platform に流す event の attributes に生本文が含まれない (hash + chars のみ)。"""
    _setup_vertex(monkeypatch)
    ev, sr, al = setup
    llm = _MockLLM([LLMResponse(text="OK")])
    from services.consultation import Consultation

    c = Consultation(
        repo=ev,
        session_repo=sr,
        analytics_logger=al,
        family_id="f1",
        line_user_id="U1",
        llm_client=llm,
    )
    user_msg = "個人情報を含む発話"
    await c.respond(user_msg)
    # 各 emit の attributes に user_msg の生文字列が含まれていない
    for e in al.events:
        attrs = e["fields"].get("attributes") or {}
        assert user_msg not in str(attrs)
        # 代わりに content_hash / content_chars がある
        if e["fields"]["action"] == "consultation_message_emitted":
            assert "content_hash" in attrs
            assert "content_chars" in attrs
