"""自動改修の流れ全体: 計画 → updater → 差分検査 → PR と自動マージ → CI → マージ → 写し → 照合 → デプロイ → 通知。

GitHub は httpx.MockTransport の偽物、uv lock は uv.lock を書き換えるだけの偽物で受ける。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import text

from src.common.db import make_engine
from src.common.migrate import upgrade
from src.common.paths import DataPaths
from src.notify.channels import GitHubIssues, LineChannel
from src.notify.pipeline import NotifyPipeline, NotifySettings
from src.remediation.github import GitHub
from src.remediation.mirror import MainMirror
from src.remediation.pipeline import PR_TEXT, RemediationPipeline, RemediationSettings
from src.remediation.tracker import track
from src.remediation.updater import UvRun, run_pending
from tests.remediation.helpers import (
    SERVICES_YAML,
    add_finding,
    detection_db,
    entry,
    lock,
)
from tests.remediation.test_mirror import tarball

REPO = "owner/mono"
BASE = "a" * 40
LOCKFILE = "examplesvc/uv.lock"
OLD = lock({"examplelib": "1.2.0", "samplehttp": "3.0.0"})
PYPROJECT = '[project]\nname = "examplesvc"\nversion = "0.1.0"\ndependencies = ["examplelib", "samplehttp"]\n'


def repo_files(uv_lock: str) -> dict[str, str]:
    return {"security-platform/config/services.yaml": SERVICES_YAML, "examplesvc/pyproject.toml": PYPROJECT,
            LOCKFILE: uv_lock, "otherexample/uv.lock": OLD}


class FakeGitHub:
    def __init__(self) -> None:
        self.head = BASE
        self.history = [BASE]  # main の履歴 (古い順)
        self.tarballs = {BASE: tarball(BASE, repo_files(OLD))}
        self.blobs: dict[str, str] = {}
        self.trees: dict[str, list[dict]] = {}
        self.commits: dict[str, dict] = {}
        self.refs: dict[str, str] = {}
        self.pulls: dict[int, dict] = {}
        self.auto_merge: list[str] = []
        self.checks: dict[str, list[dict]] = {}
        self.workflow_runs: dict[str, list[dict]] = {}
        self.jobs: dict[int, list[dict]] = {}
        self.expiration = "2027-10-31 15:00:00 UTC"
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        self.calls.append((method, path))
        headers = {"github-authentication-token-expiration": self.expiration}
        body = json.loads(request.content) if request.content else {}
        if request.url.host == "codeload.github.com":
            return httpx.Response(200, content=self.tarballs[path.rsplit("/", 1)[-1]])
        if path == "/graphql":
            self.auto_merge.append(body["variables"]["id"])
            return httpx.Response(200, json={"data": {}}, headers=headers)
        p = path.removeprefix(f"/repos/{REPO}")
        if p == "/commits/main":
            return httpx.Response(200, text=self.head, headers={**headers, "ETag": f'"{self.head}"'})
        if p.startswith("/tarball/"):
            sha = p.rsplit("/", 1)[-1]
            return httpx.Response(302, headers={"Location": f"https://codeload.github.com/{REPO}/t/{sha}"})
        if p.startswith("/git/commits/") and method == "GET":
            return httpx.Response(200, json={"sha": p.rsplit("/", 1)[-1], "tree": {"sha": "basetree"}})
        if p == "/git/blobs":
            sha = f"blob{len(self.blobs)}"
            self.blobs[sha] = body["content"]
            return httpx.Response(201, json={"sha": sha}, headers=headers)
        if p == "/git/trees":
            sha = f"tree{len(self.trees)}"
            self.trees[sha] = body["tree"]
            return httpx.Response(201, json={"sha": sha})
        if p == "/git/commits":
            sha = f"{len(self.commits) + 1:040x}"
            self.commits[sha] = body
            return httpx.Response(201, json={"sha": sha})
        if p == "/git/refs":
            self.refs[body["ref"]] = body["sha"]
            return httpx.Response(201, json={})
        if p.startswith("/git/refs/heads/") and method == "DELETE":
            self.refs.pop(p.removeprefix("/git/").replace("refs/heads/", "refs/heads/", 1), None)
            return httpx.Response(204)
        if p.startswith("/compare/"):
            base, head = p.removeprefix("/compare/").split("...")
            files = [{"filename": t["path"]} for t in self.trees[self.commits[head]["tree"]]] \
                if head in self.commits else []
            if base == head:
                status = "identical"
            elif base in self.history and head in self.history:
                status = "ahead" if self.history.index(head) > self.history.index(base) else "behind"
            else:
                status = "diverged"
            return httpx.Response(200, json={"status": status, "files": files})
        if p == "/pulls" and method == "POST":
            n = len(self.pulls) + 1
            self.pulls[n] = {**body, "number": n, "node_id": f"PR_{n}", "html_url": f"https://github.com/{REPO}/pull/{n}",
                             "state": "open", "merged": False, "mergeable_state": "blocked", "branch": body["head"],
                             "head": {"sha": self.refs[f"refs/heads/{body['head']}"]}}
            return httpx.Response(201, json=self.pulls[n])
        if p.startswith("/pulls/"):
            n = int(p.rsplit("/", 1)[-1])
            if method == "PATCH":
                self.pulls[n].update(body)
            return httpx.Response(200, json=self.pulls[n])
        if p.endswith("/check-runs"):
            return httpx.Response(200, json={"check_runs": self.checks.get(p.split("/")[2], [])})
        if p == "/actions/workflows/deploy.yml/runs":
            return httpx.Response(200, json={"workflow_runs": self.workflow_runs.get(
                request.url.params["head_sha"], [])})
        if p.startswith("/actions/runs/") and p.endswith("/jobs"):
            return httpx.Response(200, json={"jobs": self.jobs[int(p.split("/")[3])]})
        raise AssertionError((method, path))

    def merge(self, n: int, new_lock: str) -> str:
        """PR をマージしたことにして、main をマージコミットに進める。"""
        sha = "b" * 40
        self.pulls[n].update(state="closed", merged=True, merge_commit_sha=sha,
                             merged_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.head = sha
        self.history.append(sha)
        self.tarballs[sha] = tarball(sha, repo_files(new_lock))
        return sha


class FakeUv:
    def __init__(self, result: str | None = None) -> None:
        self.result = result
        self.calls: list[list[tuple[str, str]]] = []

    def __call__(self, project_dir, packages):
        self.calls.append(list(packages))
        versions = {"examplelib": "1.2.0", "samplehttp": "3.0.0", **dict(packages)}
        (project_dir / "uv.lock").write_text(self.result or lock(versions))
        return UvRun(True, "Resolved")


@pytest.fixture
def env(tmp_path):
    paths = DataPaths(tmp_path / "data")
    paths.ensure()
    upgrade("remediation", paths)
    detection = detection_db(paths)
    gh = FakeGitHub()
    client = httpx.Client(transport=httpx.MockTransport(gh))
    github = GitHub(client, REPO, token="tok")
    mirror = MainMirror(github, paths.remediation_dir)

    def make(**cfg) -> RemediationPipeline:
        return RemediationPipeline(
            make_engine(paths.sqlite_path("remediation")), mirror,
            detection=lambda: make_engine(paths.sqlite_path("detection"), read_only=True),
            jobs_dir=paths.remediation_dir / "jobs", events_dir=paths.events_dir,
            cfg=RemediationSettings(**{"open_prs": True, **cfg}),
        )

    p = make()
    p.run_mirror()
    return p, gh, detection, paths, make


def update(p: RemediationPipeline, uv: FakeUv | None = None, tmp=None) -> FakeUv:
    uv = uv or FakeUv()
    work = p.jobs_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    run_pending(p.in_dir, p.out_dir, uv, work, "uv test")
    return uv


def runs(p: RemediationPipeline) -> list:
    return p.store.runs()


def events(p: RemediationPipeline) -> list[tuple[str, dict]]:
    with p.engine.connect() as conn:
        return [(t, json.loads(pl)) for t, pl in conn.execute(text("SELECT type, payload FROM events ORDER BY seq"))]


def notify_for(paths: DataPaths) -> tuple[NotifyPipeline, list[str]]:
    upgrade("notify", paths)
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.extend(m["text"] for m in json.loads(request.content)["messages"])
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    def ro(name: str):
        return lambda: make_engine(paths.sqlite_path(name), read_only=True)

    n = NotifyPipeline(
        make_engine(paths.sqlite_path("notify")), ro("detection"), lambda: None, paths.sbom_images_dir,
        LineChannel(client, "tok", ["Uaaa"]), GitHubIssues(client, "", ""),
        NotifySettings(ZoneInfo("Asia/Tokyo"), 9, "P3", timedelta(hours=1), timedelta(days=7), {}),
        remediation=ro("remediation"),
    )
    return n, sent


def scan(detection, at: datetime) -> None:
    with detection.begin() as conn:
        conn.execute(text("INSERT INTO scan_runs (run_id, job, started_at, finished_at, status) "
                          "VALUES (:r, 'scan', :t, :t, 'success')"), {"r": f"scan_{at.timestamp()}", "t": at.isoformat()})


def test_full_flow_auto_merge_deploy_and_verify(env):
    p, gh, detection, paths, _ = env
    notify, sent = notify_for(paths)
    notify.run_events()  # 初回は今までのイベントを送らない (baseline)
    add_finding(detection, "f1", "examplesvc", "examplelib", "1.2.0", "1.3.0")
    add_finding(detection, "f2", "examplesvc", "examplelib", "1.2.0", "1.4.0", priority="P3")
    add_finding(detection, "f3", "otherexample", "examplelib", "1.2.0", "1.4.0")  # auto_remediation: false

    p.run_plan()
    [run] = runs(p)
    assert (run.service_id, run.status, run.mode, run.base_sha) == ("examplesvc", "queued", "bundle", BASE)
    assert [(x["name"], x["target"]) for x in run.packages] == [("examplelib", "1.4.0")]
    p.run_plan()
    assert len(runs(p)) == 1  # 進行中の改修があるサービスは次を始めない

    uv = update(p)
    assert uv.calls == [[("examplelib", "1.4.0")]]
    p.run_collect()
    [run] = runs(p)
    assert run.status == "pr_open" and run.pr_url.endswith("/pull/1")
    pr = gh.pulls[1]
    assert (pr["title"], pr["body"], pr["base"]) == (f"chore(examplesvc): {PR_TEXT}", PR_TEXT, "main")
    assert gh.auto_merge == ["PR_1"]
    [commit] = gh.commits.values()
    assert commit["message"] == f"chore(examplesvc): {PR_TEXT}" and commit["parents"] == [BASE]
    [tree] = gh.trees.values()
    assert [t["path"] for t in tree] == [LOCKFILE]  # lockfile 以外は変えない
    assert "examplelib" in gh.blobs["blob0"] and 'version = "1.4.0"' in gh.blobs["blob0"]
    assert not list(p.in_dir.iterdir()) and not list(p.out_dir.iterdir())  # 依頼と結果は片付ける

    gh.checks[run.head_sha] = [{"name": "CI result", "status": "in_progress", "conclusion": None}]
    p.run_track()
    assert runs(p)[0].status == "pr_open"

    merge_sha = gh.merge(1, lock({"examplelib": "1.4.0", "samplehttp": "3.0.0"}))
    p.run_track()
    assert runs(p)[0].status == "merged" and runs(p)[0].merge_sha == merge_sha
    p.run_mirror()
    p.run_track()
    run = runs(p)[0]
    assert run.status == "landed"

    p.run_track()  # landed の後の照合がまだ無い
    assert runs(p)[0].status == "landed"
    with detection.begin() as conn:
        conn.execute(text("UPDATE findings SET state = 'resolved' WHERE finding_id IN ('f1', 'f2')"))
    scan(detection, datetime.now(UTC) + timedelta(seconds=1))
    gh.workflow_runs[merge_sha] = [{"id": 7, "status": "completed", "created_at": "x", "html_url": "https://wf/7"}]
    gh.jobs[7] = [{"name": "Deploy / examplesvc", "conclusion": "success"}]
    p.run_track()
    run = runs(p)[0]
    assert (run.status, run.deploy_status) == ("verified", "success")
    assert [t for t, _ in events(p)] == ["remediation.pr_opened", "remediation.merged", "remediation.deployed"]

    notify.run_events()
    assert sent == []  # 自動マージされたものはすぐには知らせない (日次まとめに載る)
    from src.notify.remediation import digest_section
    section = digest_section(make_engine(paths.sqlite_path("remediation"), read_only=True),
                             datetime(2026, 1, 1, tzinfo=UTC))
    assert section[0] == "■ 自動改修 (前回から): PR 1 / マージ 1 / デプロイ 1 / 止まった 0"


def test_ci_failure_splits_the_service_into_single_package_runs(env):
    p, gh, detection, paths, _ = env
    notify, sent = notify_for(paths)
    notify.run_events()
    add_finding(detection, "f1", "examplesvc", "examplelib", "1.2.0", "1.4.0")
    add_finding(detection, "f2", "examplesvc", "samplehttp", "3.0.0", "3.0.2")
    p.run_plan()
    update(p)
    p.run_collect()
    [run] = runs(p)
    assert len(run.packages) == 2
    gh.checks[run.head_sha] = [{"name": "CI result", "status": "completed", "conclusion": "failure"},
                               {"name": "Claude review", "status": "completed", "conclusion": "failure"}]
    p.run_track()
    run = runs(p)[0]
    assert run.status == "ci_failed" and gh.pulls[1]["state"] == "closed"
    assert f"refs/heads/{run.branch}" not in gh.refs
    assert p.store.mode("examplesvc") == "single"

    notify.run_events()
    assert len(sent) == 1 and "CI で止まりました" in sent[0] and "CI result" in sent[0]
    assert "Claude review" not in sent[0]  # 必須のチェックだけを見る

    p.run_plan()
    queued = [r for r in runs(p) if r.status == "queued"]
    assert [[x["name"] for x in r.packages] for r in queued] == [["examplelib"]]  # 1 つずつ


def test_guard_failure_is_reported_and_not_retried(env):
    p, gh, detection, paths, _ = env
    notify, sent = notify_for(paths)
    notify.run_events()
    add_finding(detection, "f1", "examplesvc", "examplelib", "1.2.0", "1.4.0")
    p.run_plan()
    tampered = lock({"examplelib": "1.4.0", "samplehttp": "3.0.0"},
                    entries={"samplehttp": entry("samplehttp", "3.0.0", salt="swapped")})
    update(p, FakeUv(tampered))
    p.run_collect()
    [run] = runs(p)
    assert run.status == "guard_failed" and "中身が変わった" in run.detail["reason"]
    assert gh.pulls == {} and gh.commits == {}  # PR は作らない
    notify.run_events()
    assert len(sent) == 1 and "差分検査で止まりました" in sent[0]
    p.run_plan()
    assert len(runs(p)) == 1  # 同じ版では二度と試さない


def test_p1_is_not_auto_merged_and_is_notified(env):
    p, gh, detection, paths, _ = env
    notify, sent = notify_for(paths)
    notify.run_events()
    add_finding(detection, "f1", "examplesvc", "examplelib", "1.2.0", "1.4.0", priority="P1")
    p.run_plan()
    update(p)
    p.run_collect()
    [run] = runs(p)
    assert run.status == "pr_open" and run.manual
    assert gh.auto_merge == []
    notify.run_events()
    assert len(sent) == 1 and "確認してマージしてください" in sent[0] and run.pr_url in sent[0]


def test_dry_run_stops_after_the_guard(env):
    _, gh, detection, _, make = env
    p = make(open_prs=False)
    add_finding(detection, "f1", "examplesvc", "examplelib", "1.2.0", "1.4.0")
    p.run_plan()
    update(p)
    p.run_collect()
    [run] = runs(p)
    assert run.status == "dry_run" and run.detail["changes"] == ["examplelib 1.2.0 → 1.4.0"]
    assert gh.commits == {} and gh.pulls == {}


def test_stale_finding_is_not_downgraded(env):
    """照合が写しより古く、lockfile ではもう上がっているものは依頼しない。"""
    p, _, detection, _, _ = env
    add_finding(detection, "f1", "examplesvc", "examplelib", "1.0.0", "1.1.0")  # 写しは 1.2.0
    p.run_plan()
    assert runs(p) == []


def test_not_resolved_and_conflict(env):
    p, gh, detection, paths, _ = env
    notify, sent = notify_for(paths)
    notify.run_events()
    add_finding(detection, "f1", "examplesvc", "examplelib", "1.2.0", "1.4.0")
    p.run_plan()
    update(p)
    p.run_collect()
    gh.merge(1, OLD)  # マージしたが lockfile は古いまま (別の変更で戻されたなど)
    p.run_track()
    p.run_mirror()
    p.run_track()
    scan(detection, datetime.now(UTC) + timedelta(seconds=1))
    p.run_track()
    assert runs(p)[0].status == "not_resolved"
    notify.run_events()
    assert len(sent) == 1 and "Finding が閉じていません" in sent[0]

    add_finding(detection, "f9", "examplesvc", "samplehttp", "3.0.0", "3.0.2")
    p.run_plan()
    update(p)
    p.run_collect()
    gh.pulls[2]["mergeable_state"] = "dirty"
    p.run_track()
    assert runs(p)[-1].status == "conflict" and gh.pulls[2]["state"] == "closed"


def test_updater_timeout_and_token_expiry(env):
    _, _, detection, paths, make = env
    notify, sent = notify_for(paths)
    notify.run_events()
    add_finding(detection, "f1", "examplesvc", "examplelib", "1.2.0", "1.4.0")
    p = make(update_timeout=timedelta(seconds=-1))
    p.run_plan()
    p.run_collect()  # updater が結果を返さない
    assert runs(p)[0].status == "error" and "updater が応答しない" in runs(p)[0].detail["reason"]

    track(p, now=datetime(2027, 10, 20, tzinfo=UTC))  # 期限 (2027-10-31) まで 11 日
    track(p, now=datetime(2027, 10, 21, tzinfo=UTC))  # 同じ段階 (14 日を切った) では 1 回だけ
    track(p, now=datetime(2027, 10, 29, tzinfo=UTC))  # 3 日を切った
    notify.run_events()
    token = [s for s in sent if "トークン" in s]
    assert len(token) == 2 and "残り 11 日" in token[0] and "残り 2 日" in token[1]
