"""IAP JWT 検証 + email allowlist のテスト。

実 IAP JWT は GCP からしか取れないので、`google.oauth2.id_token.verify_token` を
monkeypatch してダミーの decoded payload を返す形でユニットテスト化。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _client_with_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dev_bypass: str = "false",
    allowed_emails: str = "",
    iap_audience: str = "/projects/123/global/backendServices/abc",
) -> TestClient:
    from importlib import reload

    monkeypatch.setenv("ADMIN_DEV_BYPASS", dev_bypass)
    monkeypatch.setenv("ADMIN_ALLOWED_EMAILS", allowed_emails)
    monkeypatch.setenv("ADMIN_IAP_AUDIENCE", iap_audience)

    import review_admin_ui.config as config_module

    reload(config_module)
    import review_admin_ui.auth as auth_module

    reload(auth_module)
    import review_admin_ui.main as main_module

    reload(main_module)
    return TestClient(main_module.app)


def test_dev_bypass_allows_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """dev_bypass=true なら IAP 検証スキップ + 200。"""
    client = _client_with_env(monkeypatch, dev_bypass="true")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "dev@example.com" in resp.text


def test_missing_iap_header_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_env(
        monkeypatch, dev_bypass="false", allowed_emails="op@example.com"
    )
    resp = client.get("/")
    assert resp.status_code == 401
    assert "missing IAP" in resp.json()["detail"]


def test_invalid_iap_jwt_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_env(
        monkeypatch, dev_bypass="false", allowed_emails="op@example.com"
    )
    # IAP verify を強制失敗させる
    import review_admin_ui.auth as auth_module

    def _bad_verify(token: str) -> tuple[str, str]:
        raise ValueError("bad signature")

    monkeypatch.setattr(auth_module, "_verify_iap_jwt", _bad_verify)
    resp = client.get("/", headers={"X-Goog-IAP-JWT-Assertion": "fake.jwt.token"})
    assert resp.status_code == 401
    assert "invalid IAP JWT" in resp.json()["detail"]


def test_email_not_in_allowlist_returns_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client_with_env(
        monkeypatch, dev_bypass="false", allowed_emails="op@example.com"
    )
    import review_admin_ui.auth as auth_module

    monkeypatch.setattr(
        auth_module,
        "_verify_iap_jwt",
        lambda token: ("intruder@example.com", "sub-001"),
    )
    resp = client.get("/", headers={"X-Goog-IAP-JWT-Assertion": "valid.jwt"})
    assert resp.status_code == 403
    assert "not allowed" in resp.json()["detail"]


def test_empty_allowlist_in_prod_returns_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fail-closed: allowlist 未設定なら誰も許可しない。"""
    client = _client_with_env(
        monkeypatch, dev_bypass="false", allowed_emails=""
    )
    import review_admin_ui.auth as auth_module

    monkeypatch.setattr(
        auth_module, "_verify_iap_jwt", lambda token: ("any@example.com", "sub")
    )
    resp = client.get("/", headers={"X-Goog-IAP-JWT-Assertion": "valid.jwt"})
    assert resp.status_code == 403
    assert "allowlist" in resp.json()["detail"]


def test_allowed_email_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_env(
        monkeypatch,
        dev_bypass="false",
        allowed_emails="op@example.com,backup@example.com",
    )
    import review_admin_ui.auth as auth_module

    monkeypatch.setattr(
        auth_module, "_verify_iap_jwt", lambda token: ("op@example.com", "sub-007")
    )
    resp = client.get("/", headers={"X-Goog-IAP-JWT-Assertion": "valid.jwt"})
    assert resp.status_code == 200
    assert "op@example.com" in resp.text


def test_allowed_email_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_env(
        monkeypatch, dev_bypass="false", allowed_emails="OP@example.com"
    )
    import review_admin_ui.auth as auth_module

    monkeypatch.setattr(
        auth_module, "_verify_iap_jwt", lambda token: ("op@example.com", "sub")
    )
    resp = client.get("/", headers={"X-Goog-IAP-JWT-Assertion": "valid.jwt"})
    assert resp.status_code == 200
