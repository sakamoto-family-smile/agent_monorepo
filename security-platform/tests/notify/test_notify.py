"""通知 (notify) のテスト。LINE・GitHub は httpx.MockTransport で受ける。"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import text

from src.common.db import make_engine
from src.common.migrate import upgrade
from src.notify.channels import ChannelError, GitHubIssues, LineChannel, split_text
from src.notify.pipeline import NotifyPipeline, NotifySettings
from tests.detection.test_pipeline import setup, uv_lock  # noqa: F401  (fixture)
from tests.intel.test_pipeline import env as intel_env  # noqa: F401  (fixture)

TZ = ZoneInfo("Asia/Tokyo")


class FakeApis:
    """LINE と GitHub の API を受ける。"""

    def __init__(self) -> None:
        self.line: list[dict] = []
        self.line_status = 200
        self.issues: dict[int, dict] = {}
        self.labels: set[str] = set()
        self.github_calls: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.line.me":
            if self.line_status != 200:
                return httpx.Response(self.line_status, text="boom")
            self.line.append({"headers": dict(request.headers), **json.loads(request.content)})
            return httpx.Response(200, json={})
        path = request.url.path.removeprefix("/repos/owner/findings")
        self.github_calls.append((request.method, path))
        if path.startswith("/labels/"):
            return httpx.Response(200 if path[8:] in self.labels else 404, json={})
        if path == "/labels":
            self.labels.add(json.loads(request.content)["name"])
            return httpx.Response(201, json={})
        if path == "/issues" and request.method == "POST":
            number = len(self.issues) + 1
            self.issues[number] = {**json.loads(request.content), "state": "open"}
            return httpx.Response(201, json={"number": number})
        if path.startswith("/issues/") and request.method == "PATCH":
            self.issues[int(path[8:])].update(json.loads(request.content))
            return httpx.Response(200, json={})
        raise AssertionError((request.method, path))

    def texts(self) -> list[str]:
        return [m["text"] for push in self.line for m in push["messages"]]


@pytest.fixture
def notify(setup, intel_env, tmp_path):  # noqa: F811
    make_detection, repo, *_ = setup
    paths = intel_env[3]
    upgrade("notify", paths)
    apis = FakeApis()
    client = httpx.Client(transport=httpx.MockTransport(apis))

    def make(line_token: str = "tok", gh_token: str = "ghtok") -> NotifyPipeline:
        def ro(name: str):
            return lambda: make_engine(paths.sqlite_path(name), read_only=True)
        return NotifyPipeline(
            make_engine(paths.sqlite_path("notify")), ro("detection"), ro("intel"), paths.sbom_images_dir,
            LineChannel(client, line_token, ["Uaaa"]), GitHubIssues(client, gh_token, "owner/findings"),
            NotifySettings(TZ, 9, "P3", timedelta(hours=1), timedelta(days=7),
                           {"osv": timedelta(hours=1), "kev": timedelta(hours=1)}),
        )

    return make, make_detection, repo, apis


def q(p: NotifyPipeline, sql: str) -> list[tuple]:
    with p.engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql)).all()]


def test_split_text_keeps_lines_under_limit():
    assert split_text("a\nbb\nccc", limit=4) == ["a\nbb", "ccc"]
    assert split_text("x" * 9, limit=4) == ["xxxx", "xxxx", "x"]
    assert split_text("") == [""]


def test_p1_events_baseline_then_alert_once(notify):
    make, make_detection, repo, apis = notify
    detection = make_detection()
    detection.run_scan()  # P1 2 件 (examplelib の KEV・evilpkg の悪性パッケージ)
    p = make()
    p.run_events()
    assert apis.line == []  # 導入時点の P1 は送らない
    (repo / "api/uv.lock").write_text(uv_lock(ExampleLib="2.4.3", other="1.0"))
    detection.run_scan()
    (repo / "api/uv.lock").write_text(uv_lock(ExampleLib="2.4.0", other="1.0"))
    detection.run_scan()  # 再発 (reopened, P1)
    p.run_events()
    p.run_events()
    assert len(apis.texts()) == 1
    body = apis.texts()[0]
    assert "【至急】P1 の脆弱性 1 件" in body and "api: examplelib 2.4.0 → 2.4.3" in body
    assert apis.line[0]["to"] == "Uaaa" and apis.line[0]["headers"]["x-line-retry-key"]
    assert q(p, "SELECT kind, status FROM notifications") == [("finding", "sent")]


def test_line_failure_keeps_cursor_and_unconfigured_is_skipped(notify):
    make, make_detection, repo, apis = notify
    detection = make_detection()
    detection.run_scan()
    p = make()
    p.run_events()
    (repo / "api/uv.lock").write_text(uv_lock(ExampleLib="2.4.3", other="1.0"))
    detection.run_scan()
    (repo / "api/uv.lock").write_text(uv_lock(ExampleLib="2.4.0", other="1.0"))
    detection.run_scan()
    apis.line_status = 500
    with pytest.raises(ChannelError):
        p.run_events()
    apis.line_status = 200
    p.run_events()  # 前回送れなかった分を送る
    assert len(apis.texts()) == 1

    unconfigured = make(line_token="")
    (repo / "api/uv.lock").write_text(uv_lock(ExampleLib="2.4.3", other="1.0"))
    detection.run_scan()
    (repo / "api/uv.lock").write_text(uv_lock(ExampleLib="2.4.0", other="1.0"))
    detection.run_scan()
    unconfigured.run_events()
    assert len(apis.texts()) == 1
    assert q(p, "SELECT status FROM notifications ORDER BY notification_id") == [("sent",), ("skipped",)]


def test_health_alerts_on_change_only(notify):
    make, make_detection, *_, apis = notify
    p = make()
    p.run_health()  # 照合がまだ一度も成功していない → 停止
    assert len(apis.texts()) == 1 and "停止 detection:scan" in apis.texts()[0]
    p.run_health()
    assert len(apis.texts()) == 1  # 変わっていなければ送らない
    make_detection().run_scan()
    p.run_health()
    assert "復旧 detection:scan" in apis.texts()[-1]
    assert q(p, "SELECT ok FROM alert_states WHERE key = 'detection:scan'") == [(1,)]


def test_digest_once_a_day_after_hour(notify):
    make, make_detection, *_, apis = notify
    make_detection().run_scan()
    p = make()
    morning = datetime(2026, 10, 28, 8, 0, tzinfo=TZ).astimezone(UTC)
    p.run_digest(morning)
    assert apis.line == []  # 9 時前
    p.run_digest(morning + timedelta(hours=1))
    p.run_digest(morning + timedelta(hours=5))
    assert len(apis.texts()) == 1
    body = apis.texts()[0]
    assert body.startswith("【脆弱性 日次まとめ】2026-10-28")
    assert "未対応: P1 2 / P2 0 / P3 0 / P4 0 (例外で抑止 0)" in body
    assert "■ 新規" in body and "examplelib 2.4.0 → 2.4.3" in body


def test_issues_grouped_by_package_and_closed_when_fixed(notify):
    make, make_detection, repo, apis = notify
    detection = make_detection()
    detection.run_scan()
    p = make()
    p.run_issues()
    titles = sorted(i["title"] for i in apis.issues.values())
    assert titles == ["[P1] evilpkg (npm) の脆弱性", "[P1] examplelib (PyPI) の脆弱性"]
    issue = next(i for i in apis.issues.values() if "examplelib" in i["title"])
    assert issue["labels"] == ["security", "P1"]
    assert "<!-- security-platform:group=PyPI/examplelib -->" in issue["body"]
    assert "| P1 | api | 2.4.0 | CVE-2026-1111 | 2.4.3 |" in issue["body"]
    assert {"security", "P1", "P2", "P3"} <= apis.labels

    apis.github_calls.clear()
    p.run_issues()
    assert [c for c in apis.github_calls if c[1].startswith("/issues")] == []  # 変化なし

    (repo / "api/uv.lock").write_text(uv_lock(ExampleLib="2.4.3", other="1.0"))
    detection.run_scan()
    p.run_issues()
    assert issue["state"] == "closed" and issue["title"].startswith("[解消]")
    assert q(p, "SELECT state FROM issues WHERE group_key = 'PyPI/examplelib'") == [("closed",)]

    (repo / "api/uv.lock").write_text(uv_lock(ExampleLib="2.4.0", other="1.0"))
    detection.run_scan()
    p.run_issues()
    assert issue["state"] == "open" and len(apis.issues) == 2  # 同じ Issue を開き直す


def test_issues_skipped_without_token(notify):
    make, make_detection, *_, apis = notify
    make_detection().run_scan()
    p = make(gh_token="")
    p.run_issues()
    assert apis.github_calls == []
    assert json.loads(q(p, "SELECT detail FROM job_runs WHERE job = 'notify_issues'")[0][0]) == {
        "skipped": "GitHub Issues が未設定"}


def test_versions_sorted_by_ecosystem_rules():
    from src.notify.messages import sorted_versions

    assert sorted_versions("PyPI", {"10.0", "9.0", "9.10"}) == ["9.0", "9.10", "10.0"]
    assert sorted_versions("Debian:12", {"1:0.1", "2.0-1"}) == ["2.0-1", "1:0.1"]
    assert sorted_versions("PyPI", {"1.0", "not a version"}) == ["1.0", "not a version"]
