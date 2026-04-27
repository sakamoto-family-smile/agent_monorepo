"""command_router / webhook ハンドラから business_event が emit されることを spy で検証。

`AnalyticsLogger.emit` を monkeypatch で差し替え、引数を捕捉する。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.handlers.command_router import CommandRouter, HandlerDeps
from app.repositories import InMemoryRepoBundle

LINE_USER = "U" + "0" * 32


@pytest.fixture
def captured_emits(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """emit_business_event の呼び出し引数をリストで捕捉する。

    `app.instrumentation.events.get_analytics_logger` を経由する形ではなく、
    `emit_business_event` 自体を差し替えて呼び出し回数 / 引数を取る。
    """
    captured: list[dict[str, Any]] = []

    def _spy(**kwargs: Any) -> None:
        captured.append(kwargs)

    # command_router 側の参照を差し替える（import 済みのシンボル）
    import app.handlers.command_router as cr_module
    import app.routes.line as line_module

    monkeypatch.setattr(cr_module, "emit_business_event", _spy)
    monkeypatch.setattr(line_module, "emit_business_event", _spy)
    yield captured


async def _send(deps: HandlerDeps, text: str) -> list[str]:
    return await CommandRouter(deps).dispatch_text(line_user_id=LINE_USER, text=text)


@pytest.mark.asyncio
async def test_quiz_started_event_emitted(
    deps: HandlerDeps,
    captured_emits: list[dict[str, Any]],
) -> None:
    await _send(deps, "クイズ")
    names = [e["event_name"] for e in captured_emits]
    assert "quiz_started" in names
    quiz_started = next(e for e in captured_emits if e["event_name"] == "quiz_started")
    assert "question_id" in quiz_started["properties"]
    assert "goal" in quiz_started["properties"]
    assert quiz_started["user_id"] is not None
    assert quiz_started["session_id"] is not None


@pytest.mark.asyncio
async def test_quiz_answered_event_emitted(
    deps: HandlerDeps,
    captured_emits: list[dict[str, Any]],
    repo_bundle: InMemoryRepoBundle,
) -> None:
    await _send(deps, "クイズ")
    await _send(deps, "1")
    answered = [e for e in captured_emits if e["event_name"] == "quiz_answered"]
    assert len(answered) == 1
    props = answered[0]["properties"]
    assert "question_id" in props
    assert "correct" in props
    assert isinstance(props["correct"], bool)


@pytest.mark.asyncio
async def test_mode_switched_event_emitted(
    deps: HandlerDeps,
    captured_emits: list[dict[str, Any]],
) -> None:
    await _send(deps, "ヘルプ")  # ユーザー作成のみ
    captured_emits.clear()
    await _send(deps, "モード切替")
    switched = [e for e in captured_emits if e["event_name"] == "mode_switched"]
    assert len(switched) == 1
    assert switched[0]["properties"]["from_goal"] == "provisional"
    assert switched[0]["properties"]["to_goal"] == "full"


@pytest.mark.asyncio
async def test_user_data_deleted_event_emitted(
    deps: HandlerDeps,
    captured_emits: list[dict[str, Any]],
) -> None:
    await _send(deps, "クイズ")  # ユーザー作成
    captured_emits.clear()
    await _send(deps, "データを削除")
    deleted = [e for e in captured_emits if e["event_name"] == "user_data_deleted"]
    assert len(deleted) == 1
    assert deleted[0]["properties"]["trigger"] == "user_command"


def test_emit_business_event_silently_skips_when_setup_not_called() -> None:
    """setup_observability() 未実行時に emit が例外を投げず黙って skip すること。"""
    # まずグローバル状態をクリア
    from app.instrumentation import setup as setup_module
    from app.instrumentation.events import emit_business_event

    setup_module.reset_for_tests()
    # 例外なく呼べる
    emit_business_event(event_name="test_event", properties={"x": 1}, user_id="u-1")
