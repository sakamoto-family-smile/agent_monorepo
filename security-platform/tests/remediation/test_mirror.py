"""origin/main の写し (remediation の mirror) のテスト。GitHub は httpx.MockTransport で受ける。"""
from __future__ import annotations

import io
import json
import os
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from src.common.db import make_engine
from src.common.migrate import upgrade
from src.common.paths import DataPaths
from src.notify.health import remediation_checks
from src.remediation.github import GitHub, parse_expiration
from src.remediation.mirror import MainMirror, MirrorError, current_sha
from src.remediation.pipeline import JOB_MIRROR, RemediationPipeline

REPO = "owner/mono"
SHA1, SHA2, SHA3 = "1" * 40, "2" * 40, "3" * 40
SERVICES = "security-platform/config/services.yaml"


def tarball(sha: str, files: dict[str, str], *, extra: list[tarfile.TarInfo] | None = None) -> bytes:
    """GitHub の tarball と同じ形 (先頭が ``<repo>-<sha>/``)。"""
    buf = io.BytesIO()
    top = f"mono-{sha[:7]}"
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        d = tarfile.TarInfo(top)
        d.type = tarfile.DIRTYPE
        tar.addfile(d)
        for name, body in files.items():
            data = body.encode()
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for info in extra or []:
            info.name = f"{top}/{info.name}" if not info.name.startswith("/") else info.name
            tar.addfile(info)
    return buf.getvalue()


class FakeGitHub:
    def __init__(self) -> None:
        self.head = SHA1
        self.tarballs: dict[str, bytes] = {}
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.expiration = "2027-10-31 15:00:00 UTC"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.url.host, request.url.path, dict(request.headers)))
        headers = {"github-authentication-token-expiration": self.expiration}
        if request.url.host == "codeload.github.com":
            sha = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, content=self.tarballs[sha])
        if request.url.path == f"/repos/{REPO}/commits/main":
            etag = f'"{self.head}"'
            if request.headers.get("if-none-match") == etag:
                return httpx.Response(304, headers=headers)
            return httpx.Response(200, text=self.head, headers={**headers, "ETag": etag})
        if request.url.path.startswith(f"/repos/{REPO}/tarball/"):
            sha = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(302, headers={**headers, "Location": f"https://codeload.github.com/{REPO}/legacy.tar.gz/{sha}"})
        raise AssertionError(request.url)


@pytest.fixture
def mirror(tmp_path):
    fake = FakeGitHub()
    fake.tarballs = {sha: tarball(sha, {SERVICES: f"services: []  # {sha[:4]}\n", "svc/uv.lock": sha})
                     for sha in (SHA1, SHA2, SHA3)}
    github = GitHub(httpx.Client(transport=httpx.MockTransport(fake)), REPO, token="tok")
    return MainMirror(github, tmp_path / "remediation"), fake


def test_sync_extracts_commit_and_switches_link(mirror):
    m, fake = mirror
    r = m.sync()
    assert (r.sha, r.changed, r.previous) == (SHA1, True, None)
    assert os.readlink(m.link) == f"snapshots/{SHA1}"  # 相対リンク
    assert (m.link / "svc/uv.lock").read_text() == SHA1
    assert current_sha(m.root) == SHA1
    # トークンは api.github.com にだけ送り、リダイレクト先 (codeload) には送らない
    codeload = [h for host, _, h in fake.calls if host == "codeload.github.com"]
    assert codeload and all("authorization" not in h for h in codeload)
    assert m.github.token_expires_at == datetime(2027, 10, 31, 15, tzinfo=UTC)


def test_sync_unchanged_uses_conditional_request(mirror):
    m, fake = mirror
    m.sync()
    fake.calls.clear()
    r = m.sync()
    assert (r.sha, r.changed) == (SHA1, False)
    assert [p for _, p, _ in fake.calls] == [f"/repos/{REPO}/commits/main"]  # tarball は取り直さない
    assert fake.calls[0][2]["if-none-match"] == f'"{SHA1}"'


def test_new_commit_switches_and_prunes_old_snapshots(mirror):
    m, fake = mirror
    m.sync()
    fake.head = SHA2
    r = m.sync()
    assert (r.sha, r.previous) == (SHA2, SHA1)
    assert (m.link / "svc/uv.lock").read_text() == SHA2
    assert sorted(p.name for p in m.snapshots.iterdir()) == [SHA1, SHA2]  # 1 つ前は残す
    fake.head = SHA3
    m.sync()
    assert sorted(p.name for p in m.snapshots.iterdir()) == [SHA2, SHA3]


def test_broken_tarball_keeps_previous_snapshot(mirror):
    m, fake = mirror
    m.sync()
    fake.head = SHA2
    fake.tarballs[SHA2] = tarball(SHA2, {"svc/uv.lock": "x"})  # services.yaml が無い
    with pytest.raises(MirrorError):
        m.sync()
    assert current_sha(m.root) == SHA1
    assert sorted(p.name for p in m.snapshots.iterdir()) == [SHA1]  # 展開途中のものは残さない


@pytest.mark.parametrize("make_member", [
    lambda: tarfile.TarInfo("../outside"),
    lambda: _symlink("evil", "/etc/passwd"),
    lambda: _symlink("evil", "../../../outside"),
])
def test_rejects_members_escaping_destination(mirror, make_member):
    m, fake = mirror
    fake.tarballs[SHA1] = tarball(SHA1, {SERVICES: "services: []\n"}, extra=[make_member()])
    with pytest.raises(tarfile.FilterError):
        m.sync()
    assert current_sha(m.root) is None
    assert not (m.root.parent / "outside").exists()


def _symlink(name: str, target: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    return info


def test_rejects_oversized_tarball(mirror):
    m, fake = mirror
    m.max_bytes = 100
    fake.tarballs[SHA1] = tarball(SHA1, {SERVICES: "x" * 10_000})
    with pytest.raises(MirrorError, match="MB"):
        m.sync()
    assert current_sha(m.root) is None


def test_parse_expiration():
    assert parse_expiration("2027-10-31 15:00:00 UTC") == datetime(2027, 10, 31, 15, tzinfo=UTC)
    assert parse_expiration("2027-11-01 00:00:00 +0900") == datetime(2027, 10, 31, 15, tzinfo=UTC)
    assert parse_expiration("someday") is None


def test_pipeline_records_runs_and_notify_checks_freshness(mirror, tmp_path):
    m, _ = mirror
    paths = DataPaths(tmp_path / "data")
    upgrade("remediation", paths)
    p = RemediationPipeline(make_engine(paths.sqlite_path("remediation")), m)
    ro = make_engine(paths.sqlite_path("remediation"), read_only=True)
    now = datetime.now(UTC)
    assert not remediation_checks(ro, timedelta(minutes=10), now)[0].ok  # まだ一度も取れていない
    p.run_mirror()
    with p.engine.connect() as conn:
        status, detail = conn.execute(text("SELECT status, detail FROM job_runs WHERE job = :j"),
                                      {"j": JOB_MIRROR}).one()
    assert status == "success" and json.loads(detail)["sha"] == SHA1
    assert p.last_success(JOB_MIRROR) is not None
    assert remediation_checks(ro, timedelta(minutes=10), datetime.now(UTC))[0].ok
    assert not remediation_checks(ro, timedelta(minutes=10), now + timedelta(hours=1))[0].ok
    assert remediation_checks(None, timedelta(minutes=10), now)[0].ok is False


def test_detection_reads_mirror_layout(mirror):
    """detection の REPO_DIR / SERVICES_PATH (docker-compose.yml) が写しの中を指している。"""
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    assert "REPO_DIR: /app/data/remediation/main\n" in compose
    assert f"SERVICES_PATH: /app/data/remediation/main/{SERVICES}\n" in compose
    m, _ = mirror
    m.sync()
    assert (m.link / SERVICES).is_file()
