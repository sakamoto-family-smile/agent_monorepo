"""review-admin-ui: 本番相当 (ADMIN_ENV=gcp / Cloud Run) での安全側設定のテスト。

- ADMIN_SESSION_SECRET_KEY 未設定なら起動拒否
- ADMIN_DEV_BYPASS=true なら起動拒否 (+ require_admin でも無効化)
- /docs・/redoc・/openapi.json を公開しない
"""

from __future__ import annotations

from importlib import reload

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from review_admin_ui.config import AdminSettings

DOC_PATHS = ("/docs", "/redoc", "/openapi.json")
_SECRET = "test-session-secret-32-bytes-min!!"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "K_SERVICE",
        "ADMIN_ENV",
        "ADMIN_DEV_BYPASS",
        "ADMIN_SESSION_SECRET_KEY",
        "ADMIN_ENABLE_API_DOCS",
        "ADMIN_ALLOWED_EMAILS",
    ):
        monkeypatch.delenv(name, raising=False)


def _settings() -> AdminSettings:
    return AdminSettings(_env_file=None)


def _reload_app() -> TestClient:
    import review_admin_ui.config as config_module

    reload(config_module)
    import review_admin_ui.auth as auth_module

    reload(auth_module)
    import review_admin_ui.main as main_module

    reload(main_module)
    return TestClient(main_module.create_app())


# ---- ADMIN_SESSION_SECRET_KEY ----


def test_gcp_env_without_session_secret_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_ENV", "gcp")
    with pytest.raises(ValidationError, match="ADMIN_SESSION_SECRET_KEY"):
        _settings()


def test_gcp_env_with_blank_session_secret_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_ENV", "gcp")
    monkeypatch.setenv("ADMIN_SESSION_SECRET_KEY", "   ")
    with pytest.raises(ValidationError, match="ADMIN_SESSION_SECRET_KEY"):
        _settings()


def test_cloud_run_without_admin_env_still_requires_session_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADMIN_ENV の設定漏れ (既定 local) でも Cloud Run 上なら本番扱い。"""
    monkeypatch.setenv("K_SERVICE", "driving-license-bot-admin")
    with pytest.raises(ValidationError, match="ADMIN_SESSION_SECRET_KEY"):
        _settings()


def test_gcp_env_with_session_secret_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_ENV", "gcp")
    monkeypatch.setenv("ADMIN_SESSION_SECRET_KEY", _SECRET)
    s = _settings()
    assert s.is_local_env is False
    assert s.session_secret_key == _SECRET


def test_local_env_without_session_secret_is_allowed() -> None:
    """ローカル開発では従来通り fallback 鍵で起動できる。"""
    s = _settings()
    assert s.is_local_env is True
    assert s.session_secret_key == ""


# ---- ADMIN_DEV_BYPASS ----


def test_gcp_env_with_dev_bypass_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_ENV", "gcp")
    monkeypatch.setenv("ADMIN_SESSION_SECRET_KEY", _SECRET)
    monkeypatch.setenv("ADMIN_DEV_BYPASS", "true")
    with pytest.raises(ValidationError, match="ADMIN_DEV_BYPASS"):
        _settings()


def test_cloud_run_with_dev_bypass_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("K_SERVICE", "driving-license-bot-admin")
    monkeypatch.setenv("ADMIN_SESSION_SECRET_KEY", _SECRET)
    monkeypatch.setenv("ADMIN_DEV_BYPASS", "true")
    with pytest.raises(ValidationError, match="ADMIN_DEV_BYPASS"):
        _settings()


def test_dev_bypass_active_is_false_outside_local() -> None:
    """validator を経由しない経路でも dev_bypass_active は本番相当で False (多重防御)。"""
    s = AdminSettings.model_construct(env="gcp", dev_bypass=True)
    assert s.dev_bypass_active is False


def test_dev_bypass_active_in_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_DEV_BYPASS", "true")
    assert _settings().dev_bypass_active is True


def test_gcp_env_index_requires_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_ENV", "gcp")
    monkeypatch.setenv("ADMIN_SESSION_SECRET_KEY", _SECRET)
    monkeypatch.setenv("ADMIN_ALLOWED_EMAILS", "op@example.com")
    client = _reload_app()
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


# ---- API docs ----


def test_docs_disabled_in_gcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_ENV", "gcp")
    monkeypatch.setenv("ADMIN_SESSION_SECRET_KEY", _SECRET)
    client = _reload_app()
    for path in DOC_PATHS:
        assert client.get(path, follow_redirects=False).status_code == 404, path
    assert client.get("/healthz").status_code == 200


def test_docs_enabled_in_local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _reload_app()
    for path in DOC_PATHS:
        assert client.get(path).status_code == 200, path


def test_docs_enabled_by_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_ENV", "gcp")
    monkeypatch.setenv("ADMIN_SESSION_SECRET_KEY", _SECRET)
    monkeypatch.setenv("ADMIN_ENABLE_API_DOCS", "true")
    client = _reload_app()
    for path in DOC_PATHS:
        assert client.get(path).status_code == 200, path
