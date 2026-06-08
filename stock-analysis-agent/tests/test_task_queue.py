"""Cloud Tasks enqueue (PROPOSAL-0011 P3-A) の unit テスト。"""

from __future__ import annotations

import json

import pytest

import config
from services import task_queue


class _FakeTasksClient:
    last_request = None

    def create_task(self, request):
        _FakeTasksClient.last_request = request
        return {"name": "fake/task/1"}


@pytest.fixture
def _patched(monkeypatch):
    from google.cloud import tasks_v2

    monkeypatch.setattr(tasks_v2, "CloudTasksClient", _FakeTasksClient)
    monkeypatch.setattr(
        config.settings,
        "tasks_queue",
        "projects/p/locations/asia-northeast1/queues/stock-analysis",
    )
    monkeypatch.setattr(
        config.settings, "tasks_worker_url", "https://worker.example/api/tasks/analyze"
    )
    monkeypatch.setattr(config.settings, "tasks_invoker_sa", "inv@p.iam.gserviceaccount.com")
    _FakeTasksClient.last_request = None
    return _FakeTasksClient


def test_enqueue_builds_request(_patched):
    task_queue.enqueue_analysis("U_a", "トヨタ")
    req = _patched.last_request
    assert req["parent"] == "projects/p/locations/asia-northeast1/queues/stock-analysis"
    http = req["task"]["http_request"]
    assert http["url"] == "https://worker.example/api/tasks/analyze"
    assert json.loads(http["body"]) == {"user_id": "U_a", "target": "トヨタ"}
    assert http["oidc_token"]["service_account_email"] == "inv@p.iam.gserviceaccount.com"
    assert http["oidc_token"]["audience"] == "https://worker.example/api/tasks/analyze"


def test_enqueue_without_invoker_sa_omits_oidc(_patched, monkeypatch):
    monkeypatch.setattr(config.settings, "tasks_invoker_sa", "")
    task_queue.enqueue_analysis("U_a", "AAPL")
    http = _patched.last_request["task"]["http_request"]
    assert "oidc_token" not in http


def test_enqueue_missing_config_raises(monkeypatch):
    monkeypatch.setattr(config.settings, "tasks_queue", "")
    monkeypatch.setattr(config.settings, "tasks_worker_url", "")
    with pytest.raises(RuntimeError):
        task_queue.enqueue_analysis("U_a", "x")
