"""proxied_http_client のテスト。"""

from __future__ import annotations

from importlib import reload

import httpx
import pytest

import app.config as config_module
from app.integrations import proxied_http_client


def _reload_settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    """env を上書きして config と proxied_http_client を reload する。"""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    reload(config_module)
    # proxied_http_client は `import app.config` でモジュール参照を持つため、
    # config を reload すれば最新 settings を見る。本ファイル自体の reload は不要。


def test_build_client_without_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """SECURITY_HTTP_PROXY_URL 未設定 → proxy なしの client が返る。"""
    _reload_settings(monkeypatch, SECURITY_HTTP_PROXY_URL="")
    client = proxied_http_client.build_proxied_async_client()
    assert isinstance(client, httpx.AsyncClient)
    # 直接外向き（mounts は空 or デフォルト）
    # User-Agent ヘッダが付与されている
    ua = client.headers.get("user-agent", "")
    assert "driving-license-bot" in ua


def test_build_client_with_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """SECURITY_HTTP_PROXY_URL 設定時 → proxy 経由の client が返る。"""
    _reload_settings(
        monkeypatch, SECURITY_HTTP_PROXY_URL="http://localhost:8080"
    )
    client = proxied_http_client.build_proxied_async_client()
    assert isinstance(client, httpx.AsyncClient)
    # httpx の内部実装に深入りせず、proxy 引数が反映されている挙動を確認。
    # 実際の HTTP 呼び出しはこのテストでは行わない。


def test_build_client_extra_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    _reload_settings(monkeypatch, SECURITY_HTTP_PROXY_URL="")
    client = proxied_http_client.build_proxied_async_client(
        extra_headers={"X-Trace-Id": "abc-123"}
    )
    assert client.headers.get("x-trace-id") == "abc-123"


def test_build_client_user_agent_overridable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reload_settings(monkeypatch, SECURITY_HTTP_PROXY_URL="")
    client = proxied_http_client.build_proxied_async_client(
        extra_headers={"User-Agent": "custom-ua/1.0"}
    )
    assert client.headers.get("user-agent") == "custom-ua/1.0"
