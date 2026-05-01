"""operator_notify (Phase 2-B3) のテスト。

LineBotClient を monkeypatch してネット呼び出しせずに検証。
"""

from __future__ import annotations

import pytest


def _reset_line_client() -> None:
    from app.services.line_client import reset_line_bot_client

    reset_line_bot_client()


def test_notify_operators_skip_when_no_operators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """operator_user_id_set が空 → 0 を返して send されない。"""
    from importlib import reload

    monkeypatch.setenv("OPERATOR_LINE_USER_IDS", "")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "secret")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    import app.config as config_module

    reload(config_module)
    _reset_line_client()

    import app.handlers.operator_notify as on_module

    reload(on_module)
    sent = on_module.notify_operators(["hello"])
    assert sent == 0


def test_notify_operators_skip_when_line_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LINE 未設定 (secret/token 空) → 0 を返す。"""
    from importlib import reload

    monkeypatch.setenv("OPERATOR_LINE_USER_IDS", "U123")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    import app.config as config_module

    reload(config_module)
    _reset_line_client()

    import app.handlers.operator_notify as on_module

    reload(on_module)
    sent = on_module.notify_operators(["hello"])
    assert sent == 0


def test_notify_operators_pushes_to_each_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 ユーザー登録 → push_text が 3 回呼ばれる。"""
    from importlib import reload

    monkeypatch.setenv("OPERATOR_LINE_USER_IDS", "U1,U2,U3")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "secret")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    import app.config as config_module

    reload(config_module)
    _reset_line_client()

    import app.services.line_client as lc_module

    reload(lc_module)

    pushed: list[tuple[str, list[str]]] = []

    def _fake_push(self, user_id: str, messages: list[str]) -> None:  # noqa: ARG001
        pushed.append((user_id, messages))

    monkeypatch.setattr(lc_module.LineBotClient, "push_text", _fake_push)

    import app.handlers.operator_notify as on_module

    reload(on_module)
    sent = on_module.notify_operators(["alert!"])
    assert sent == 3
    assert {u for u, _ in pushed} == {"U1", "U2", "U3"}
    assert all(msgs == ["alert!"] for _, msgs in pushed)


def test_notify_operators_continues_on_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1 user が例外 → 他は届ける、戻り値は成功数のみ。"""
    from importlib import reload

    monkeypatch.setenv("OPERATOR_LINE_USER_IDS", "U1,U2,U3")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "secret")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    import app.config as config_module

    reload(config_module)
    _reset_line_client()

    import app.services.line_client as lc_module

    reload(lc_module)

    def _flaky_push(self, user_id: str, messages: list[str]) -> None:  # noqa: ARG001
        if user_id == "U2":
            raise RuntimeError("boom")

    monkeypatch.setattr(lc_module.LineBotClient, "push_text", _flaky_push)

    import app.handlers.operator_notify as on_module

    reload(on_module)
    sent = on_module.notify_operators(["alert!"])
    assert sent == 2  # U1 と U3 は通る


def test_notify_operators_empty_messages_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空 messages → 即 0 で返す (LINE API 呼び出しもしない)。"""
    monkeypatch.setenv("OPERATOR_LINE_USER_IDS", "U1")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "secret")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    from importlib import reload

    import app.config as config_module

    reload(config_module)
    _reset_line_client()

    import app.handlers.operator_notify as on_module

    reload(on_module)
    sent = on_module.notify_operators([])
    assert sent == 0
