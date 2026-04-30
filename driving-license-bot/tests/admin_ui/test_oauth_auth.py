"""require_admin (Google OAuth + session cookie) のテスト。

OAuth flow 全体は authlib + 外部 IdP に依存するので、ここでは
session cookie に email を直接書いて gate (require_admin) の挙動を検証する。
OAuth callback の token decode 部分は authlib に任せる範囲。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _client_with_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dev_bypass: str = "false",
    allowed_emails: str = "",
    session_secret_key: str = "test-session-secret-32-bytes-min!!",
) -> TestClient:
    from importlib import reload

    monkeypatch.setenv("ADMIN_DEV_BYPASS", dev_bypass)
    monkeypatch.setenv("ADMIN_ALLOWED_EMAILS", allowed_emails)
    monkeypatch.setenv("ADMIN_SESSION_SECRET_KEY", session_secret_key)

    import review_admin_ui.config as config_module

    reload(config_module)
    import review_admin_ui.auth as auth_module

    reload(auth_module)
    import review_admin_ui.main as main_module

    reload(main_module)
    return TestClient(main_module.app)


def _set_session_email(client: TestClient, email: str) -> None:
    """session cookie に email を仕込む。

    Starlette SessionMiddleware は内部で itsdangerous で署名するので、
    test client では session を mutate する dummy endpoint 経由で設定する
    のが安全。ここでは TestClient.app の SessionMiddleware と同 secret_key
    で itsdangerous Signer を使って encode する。
    """
    import base64
    import json

    import itsdangerous

    from review_admin_ui.auth import SESSION_USER_KEY
    from review_admin_ui.config import settings

    data = {SESSION_USER_KEY: email}
    payload = base64.b64encode(json.dumps(data).encode("utf-8"))
    signer = itsdangerous.TimestampSigner(settings.session_secret_key)
    signed = signer.sign(payload)
    client.cookies.set("session", signed.decode("utf-8"))


def test_dev_bypass_allows_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """dev_bypass=true なら OAuth flow スキップ + 200。"""
    client = _client_with_env(monkeypatch, dev_bypass="true")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "dev@example.com" in resp.text


def test_unauthenticated_redirects_to_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """session 無しで保護 endpoint にアクセス → /login に 303。"""
    client = _client_with_env(monkeypatch, dev_bypass="false", allowed_emails="op@example.com")
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_email_not_in_allowlist_returns_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """allowlist 外の email を session に持っていると 403。"""
    client = _client_with_env(monkeypatch, dev_bypass="false", allowed_emails="op@example.com")
    _set_session_email(client, "intruder@example.com")
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 403
    assert "not allowed" in resp.json()["detail"]


def test_empty_allowlist_in_prod_returns_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fail-closed: allowlist 未設定なら誰も許可しない。"""
    client = _client_with_env(monkeypatch, dev_bypass="false", allowed_emails="")
    _set_session_email(client, "any@example.com")
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 403


def test_allowed_email_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_env(
        monkeypatch,
        dev_bypass="false",
        allowed_emails="op@example.com,backup@example.com",
    )
    _set_session_email(client, "op@example.com")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "op@example.com" in resp.text


def test_allowed_email_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_env(monkeypatch, dev_bypass="false", allowed_emails="OP@example.com")
    _set_session_email(client, "op@example.com")
    resp = client.get("/")
    assert resp.status_code == 200


def test_logout_clears_session(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_env(monkeypatch, dev_bypass="false", allowed_emails="op@example.com")
    _set_session_email(client, "op@example.com")

    # logout
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"

    # logout 後はクッキーが空 (or 上書き) なので redirect
    client.cookies.clear()
    resp2 = client.get("/", follow_redirects=False)
    assert resp2.status_code == 303
