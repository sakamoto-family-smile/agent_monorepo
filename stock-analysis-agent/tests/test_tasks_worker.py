"""worker エンドポイント /api/tasks/analyze (PROPOSAL-0011 P3-A) の unit テスト。

route 関数を直接呼ぶ。OIDC は TASKS_INVOKER_SA 未設定で skip される。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import config
from routes import tasks as tasks_route
from services.line_client import set_line_bot_client

pytestmark = pytest.mark.asyncio


class _StubClient:
    def __init__(self):
        self.pushes = []

    async def push_text(self, *, to, text):
        self.pushes.append({"to": to, "text": text})

    async def push_flex(self, *, to, alt_text, contents):
        self.pushes.append({"to": to, "type": "flex"})

    async def push_image(self, *, to, original_content_url, preview_image_url):
        self.pushes.append({"to": to, "type": "image"})

    async def reply_text(self, *, reply_token, text):
        pass

    async def reply_flex(self, *, reply_token, alt_text, contents):
        pass

    async def close(self):
        pass


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _no_oidc(monkeypatch):
    monkeypatch.setattr(config.settings, "tasks_invoker_sa", "")
    monkeypatch.setattr(config.settings, "tasks_max_attempts", 3)
    stub = _StubClient()
    set_line_bot_client(stub)
    yield stub
    set_line_bot_client(None)


async def test_success(monkeypatch, _no_oidc):
    called = {}

    async def fake_run(deps, *, to, target):
        called["to"] = to
        called["target"] = target

    monkeypatch.setattr(tasks_route, "run_and_deliver_analysis", fake_run)
    resp = await tasks_route.analyze_task(
        _FakeRequest({"user_id": "U_a", "target": "トヨタ"}),
        authorization=None,
        x_cloudtasks_taskretrycount=0,
    )
    assert resp["status"] == "ok"
    assert called == {"to": "U_a", "target": "トヨタ"}


async def test_missing_fields_400(_no_oidc):
    with pytest.raises(HTTPException) as ei:
        await tasks_route.analyze_task(
            _FakeRequest({"user_id": "U_a"}), authorization=None, x_cloudtasks_taskretrycount=0
        )
    assert ei.value.status_code == 400


async def test_no_line_client_acks(monkeypatch):
    set_line_bot_client(None)
    monkeypatch.setattr(config.settings, "tasks_invoker_sa", "")
    resp = await tasks_route.analyze_task(
        _FakeRequest({"user_id": "U_a", "target": "x"}),
        authorization=None,
        x_cloudtasks_taskretrycount=0,
    )
    assert resp["status"] == "skipped_no_line_client"


async def test_failure_under_limit_retries(monkeypatch, _no_oidc):
    async def boom(deps, *, to, target):
        raise RuntimeError("yfinance down")

    monkeypatch.setattr(tasks_route, "run_and_deliver_analysis", boom)
    # attempt = 0+1 = 1 < 3 → 500 で retry
    with pytest.raises(HTTPException) as ei:
        await tasks_route.analyze_task(
            _FakeRequest({"user_id": "U_a", "target": "x"}),
            authorization=None,
            x_cloudtasks_taskretrycount=0,
        )
    assert ei.value.status_code == 500
    assert _no_oidc.pushes == []  # まだユーザ通知しない


async def test_failure_at_limit_notifies(monkeypatch, _no_oidc):
    async def boom(deps, *, to, target):
        raise RuntimeError("yfinance down")

    monkeypatch.setattr(tasks_route, "run_and_deliver_analysis", boom)
    # attempt = 2+1 = 3 == max → ユーザ通知して 200
    resp = await tasks_route.analyze_task(
        _FakeRequest({"user_id": "U_a", "target": "トヨタ"}),
        authorization=None,
        x_cloudtasks_taskretrycount=2,
    )
    assert resp["status"] == "failed_notified"
    assert any("失敗" in p["text"] for p in _no_oidc.pushes)


# ---------------------------------------------------------------------------
# OIDC 検証 (_verify_oidc)
# 他テストが config を reload するため、route が参照する settings を直接 patch する。
# ---------------------------------------------------------------------------


async def test_missing_invoker_sa_rejected_outside_local(monkeypatch):
    """本番等で TASKS_INVOKER_SA が未設定なら検証 skip せず 503 (fail-closed)。"""
    monkeypatch.setattr(tasks_route.settings, "tasks_invoker_sa", "")
    monkeypatch.setattr(tasks_route.settings, "app_env", "prod")
    with pytest.raises(HTTPException) as ei:
        tasks_route._verify_oidc("Bearer x")
    assert ei.value.status_code == 503


async def test_missing_bearer_401(monkeypatch):
    monkeypatch.setattr(tasks_route.settings, "tasks_invoker_sa", "inv@p.iam.gserviceaccount.com")
    with pytest.raises(HTTPException) as ei:
        tasks_route._verify_oidc(None)
    assert ei.value.status_code == 401


async def test_oidc_audience_is_service_url_and_email_checked(monkeypatch):
    from google.oauth2 import id_token

    monkeypatch.setattr(tasks_route.settings, "tasks_invoker_sa", "inv@p.iam.gserviceaccount.com")
    monkeypatch.setattr(
        tasks_route.settings, "tasks_worker_url", "https://worker.example/api/tasks/analyze"
    )
    seen = {}

    def _verify(token, request, audience=None):
        seen["audience"] = audience
        return {"email": "other@p.iam.gserviceaccount.com"}

    monkeypatch.setattr(id_token, "verify_oauth2_token", _verify)
    with pytest.raises(HTTPException) as ei:
        tasks_route._verify_oidc("Bearer tok")
    assert ei.value.status_code == 403
    assert seen["audience"] == "https://worker.example"
