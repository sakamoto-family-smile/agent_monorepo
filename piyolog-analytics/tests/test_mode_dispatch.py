"""Phase 3-C: line_handler の mode dispatch + consult enter/exit のテスト。

Consultation の実 LLM 呼び出しはせず、mock で挙動を確認する。

NOTE: services.line_client / services.line_handler は test_line_webhook.py で
reload されるため、本ファイルでは module level import を避け、各 test 内で
lazy import して最新版の class identity を取得する (isinstance 整合性保持)。
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest
from repositories.event_repo import EventRepo
from repositories.session_repo import MODE_CONSULTING, MODE_NORMAL, SessionRepo


class _FakeLineClient:
    def __init__(self) -> None:
        self.replies: list[tuple[str, str]] = []
        self.linked: list[tuple[str, str]] = []
        self.unlinked: list[str] = []
        self.images_pushed: list[str] = []

    async def reply_text(self, *, reply_token: str, text: str) -> None:
        self.replies.append((reply_token, text))

    async def reply_image(self, *, reply_token: str, image_url: str, preview_url=None) -> None:
        self.images_pushed.append(image_url)

    async def push_text(self, *, to: str, text: str) -> None:
        pass

    async def push_image(self, *, to: str, image_url: str, preview_url=None) -> None:
        pass

    async def link_richmenu_to_user(self, *, user_id: str, rich_menu_id: str) -> None:
        self.linked.append((user_id, rich_menu_id))

    async def unlink_richmenu_from_user(self, *, user_id: str) -> None:
        self.unlinked.append(user_id)

    async def fetch_message_content(self, *, message_id: str) -> bytes:
        return b""

    async def close(self) -> None:
        pass


class _FakeAnalyticsLogger:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, **kwargs):
        self.events.append(kwargs)


@pytest.fixture
async def env(monkeypatch: pytest.MonkeyPatch):
    """EventRepo + SessionRepo + FakeLineClient を組み立てた deps。"""
    from services.line_handler import HandlerDeps

    with tempfile.TemporaryDirectory() as td:
        db = pathlib.Path(td) / "test.db"
        ev = EventRepo(database_url=f"sqlite+aiosqlite:///{db}")
        await ev.initialize()
        sr = SessionRepo(engine=ev.engine)
        client = _FakeLineClient()
        al = _FakeAnalyticsLogger()
        deps = HandlerDeps(
            line_client=client,
            repo=ev,
            family_id="f1",
            family_user_ids=frozenset({"U1"}),
            default_child_id="default",
            upload_max_bytes=1024,
            schedule_background=lambda f: None,
            session_repo=sr,
            analytics_logger=al,
            rich_menu_id_consulting="richmenu-consulting",
        )
        yield deps, client, sr, al
        await ev.dispose()


def _make_text_event(line_user_id: str, reply_token: str, text: str):
    """services.line_client の最新版 LineTextEvent を取得して生成。"""
    from services.line_client import LineTextEvent

    return LineTextEvent(
        event_type="text",
        line_user_id=line_user_id,
        reply_token=reply_token,
        text=text,
    )


def _make_postback_event(line_user_id: str, reply_token: str, data: str):
    from services.line_client import LinePostbackEvent

    return LinePostbackEvent(
        event_type="postback",
        line_user_id=line_user_id,
        reply_token=reply_token,
        data=data,
    )


def _handle_event():
    """handle_event の最新参照を返す。"""
    from services.line_handler import handle_event

    return handle_event


def _consult_replies():
    from services.line_handler import CONSULT_ENTER_REPLY, CONSULT_EXIT_REPLY

    return CONSULT_ENTER_REPLY, CONSULT_EXIT_REPLY


@pytest.mark.asyncio
async def test_text_consult_enters_mode(env) -> None:
    """テキスト「相談」で consulting mode に入り rich menu link + welcome。"""
    deps, client, sr, _ = env
    enter_reply, _ = _consult_replies()
    ev = _make_text_event("U1", "rt1", "相談")
    await _handle_event()(ev, deps)
    assert client.replies == [("rt1", enter_reply)]
    assert client.linked == [("U1", "richmenu-consulting")]
    assert (await sr.get_mode(line_user_id="U1")) == MODE_CONSULTING


@pytest.mark.asyncio
async def test_text_exit_back_to_normal(env) -> None:
    deps, client, sr, _ = env
    _, exit_reply = _consult_replies()
    await sr.set_mode(line_user_id="U1", family_id="f1", mode=MODE_CONSULTING)
    ev = _make_text_event("U1", "rt1", "相談終了")
    await _handle_event()(ev, deps)
    assert client.replies == [("rt1", exit_reply)]
    assert client.unlinked == ["U1"]
    assert (await sr.get_mode(line_user_id="U1")) == MODE_NORMAL


@pytest.mark.asyncio
async def test_postback_consult_enter(env) -> None:
    deps, client, sr, _ = env
    enter_reply, _ = _consult_replies()
    ev = _make_postback_event("U1", "rt1", "action=consult&op=enter")
    await _handle_event()(ev, deps)
    assert client.replies == [("rt1", enter_reply)]
    assert client.linked == [("U1", "richmenu-consulting")]
    assert (await sr.get_mode(line_user_id="U1")) == MODE_CONSULTING


@pytest.mark.asyncio
async def test_postback_consult_exit(env) -> None:
    deps, client, sr, _ = env
    _, exit_reply = _consult_replies()
    await sr.set_mode(line_user_id="U1", family_id="f1", mode=MODE_CONSULTING)
    ev = _make_postback_event("U1", "rt1", "action=consult&op=exit")
    await _handle_event()(ev, deps)
    assert client.replies == [("rt1", exit_reply)]
    assert client.unlinked == ["U1"]
    assert (await sr.get_mode(line_user_id="U1")) == MODE_NORMAL


@pytest.mark.asyncio
async def test_normal_mode_text_routes_to_command_router(env) -> None:
    """normal mode 中の通常テキストは command_router (HELP_TEXT 等) に流れる。"""
    deps, client, _, _ = env
    ev = _make_text_event("U1", "rt1", "ヘルプ")
    await _handle_event()(ev, deps)
    assert len(client.replies) == 1
    _, text = client.replies[0]
    assert "ぴよログ分析" in text


@pytest.mark.asyncio
async def test_consulting_text_with_emergency_returns_emergency_reply(env) -> None:
    """consulting mode 中に緊急ワード → LLM を呼ばずに #8000 案内。"""
    deps, client, sr, al = env
    await sr.set_mode(line_user_id="U1", family_id="f1", mode=MODE_CONSULTING)
    ev = _make_text_event("U1", "rt1", "40度の高熱でけいれんしてます")
    await _handle_event()(ev, deps)
    assert len(client.replies) == 1
    _, text = client.replies[0]
    assert "#8000" in text or "119" in text
    # consultation_message_emitted 等の analytics は emit されない (LLM 不通)
    actions = [e["fields"].get("action") for e in al.events]
    assert "consultation_message_emitted" not in actions


@pytest.mark.asyncio
async def test_consulting_mode_dispatch_to_consultation(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """consulting mode 中の通常テキスト → Consultation.respond が呼ばれる。"""
    deps, client, sr, _ = env
    await sr.set_mode(line_user_id="U1", family_id="f1", mode=MODE_CONSULTING)

    # Consultation.respond を mock (line_handler の最新参照)
    captured: list[str] = []

    async def fake_respond(self, user_message: str) -> str:  # noqa: ARG001
        captured.append(user_message)
        return "FAKE LLM REPLY"

    import services.line_handler as lh

    monkeypatch.setattr(lh.Consultation, "respond", fake_respond)

    ev = _make_text_event("U1", "rt1", "2 月のミルク量は?")
    await _handle_event()(ev, deps)
    assert captured == ["2 月のミルク量は?"]
    assert client.replies == [("rt1", "FAKE LLM REPLY")]
