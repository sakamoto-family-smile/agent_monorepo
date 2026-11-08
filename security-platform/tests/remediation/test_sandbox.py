"""依頼のやり取り (jobs)・隔離した更新役 (updater)・通信を絞るプロキシ (egress)。"""
from __future__ import annotations

import asyncio
import json

import pytest

from src.remediation import egress, jobs
from src.remediation.jobs import InvalidJob, UpdateJob, UpdateResult
from src.remediation.updater import UvRun, process, run_pending
from tests.remediation.helpers import PYPROJECT, write_repo

RUN = "rem_0123456789abcdef"


@pytest.fixture
def snapshot(tmp_path):
    root = tmp_path / "snap"
    write_repo(root, {
        "examplesvc/pyproject.toml": PYPROJECT, "examplesvc/uv.lock": "old lock\n", "examplesvc/app.py": "",
        "examplecommon/pyproject.toml": '[project]\nname = "examplecommon"\nversion = "1"\n',
        "unrelated/secret.txt": "not copied",
    })
    return root


def test_project_closure_follows_path_dependencies(snapshot):
    assert jobs.project_closure(snapshot, "examplesvc") == ["examplesvc", "examplecommon"]


def test_project_closure_rejects_paths_outside_the_repository(snapshot, tmp_path):
    (snapshot / "examplesvc/pyproject.toml").write_text(
        '[project]\nname = "x"\n[tool.uv.sources]\nevil = { path = "../../outside" }\n')
    (tmp_path / "outside").mkdir()
    with pytest.raises(InvalidJob, match="outside"):
        jobs.project_closure(snapshot, "examplesvc")


def test_write_and_read_job(snapshot, tmp_path):
    in_dir = tmp_path / "in"
    job = UpdateJob(RUN, "examplesvc", (("examplelib", "1.4.0"),))
    assert jobs.write_job(in_dir, job, snapshot) == ["examplesvc", "examplecommon"]
    assert (in_dir / RUN / "tree/examplesvc/uv.lock").read_text() == "old lock\n"
    assert not (in_dir / RUN / "tree/unrelated").exists()  # 対象と path 依存だけを渡す
    assert jobs.list_jobs(in_dir) == [RUN]
    assert jobs.read_job(in_dir, RUN) == job


@pytest.mark.parametrize("job", [
    UpdateJob("rem_bad", "examplesvc", (("examplelib", "1.4.0"),)),
    UpdateJob(RUN, "../escape", (("examplelib", "1.4.0"),)),
    UpdateJob(RUN, "examplesvc", (("examplelib; rm -rf /", "1.4.0"),)),
    UpdateJob(RUN, "examplesvc", (("examplelib", "1.4.0 --index-url=http://evil"),)),
    UpdateJob(RUN, "examplesvc", ()),
])
def test_job_validation(job):
    with pytest.raises(InvalidJob):
        job.validate()


def test_read_result_rejects_garbage(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    assert jobs.read_result(out, RUN) is None
    (out / f"{RUN}.json").write_text(json.dumps({"format": 1, "run_id": "rem_other", "ok": True}))
    with pytest.raises(InvalidJob):
        jobs.read_result(out, RUN)
    (out / f"{RUN}.json").write_text(json.dumps({"format": 1, "run_id": RUN, "ok": True, "lock": 5}))
    with pytest.raises(InvalidJob):
        jobs.read_result(out, RUN)


# ── updater ───────────────────────────────────────────────────────────────
class FakeUv:
    """引っかかるパッケージ (fail) を含むと失敗する uv lock。成功したら uv.lock に指定を書く。"""

    def __init__(self, fail: set[str] = frozenset(), conflict: bool = False) -> None:
        self.fail = fail
        self.conflict = conflict
        self.calls: list[list[tuple[str, str]]] = []

    def __call__(self, project_dir, packages):
        self.calls.append(list(packages))
        names = {n for n, _ in packages}
        if names & self.fail:
            return UvRun(False, f"error: No solution found when resolving: {sorted(names & self.fail)}")
        if self.conflict and len(packages) > 1:
            return UvRun(False, "error: conflicting requirements")
        (project_dir / "uv.lock").write_text(" ".join(f"{n}=={v}" for n, v in packages))
        return UvRun(True, "Resolved 3 packages")


@pytest.fixture
def tree(snapshot, tmp_path):
    in_dir = tmp_path / "in"
    jobs.write_job(in_dir, UpdateJob(RUN, "examplesvc", (("examplelib", "1.4.0"),)), snapshot)
    return in_dir / RUN / "tree"


def job_of(*names: str) -> UpdateJob:
    return UpdateJob(RUN, "examplesvc", tuple((n, "9.9") for n in names))


def test_process_all_at_once(tree, tmp_path):
    r = process(job_of("a", "b"), tree, FakeUv(), tmp_path)
    assert (r.ok, r.lock, r.applied, r.failed) == (True, "a==9.9 b==9.9", ("a", "b"), ())
    assert (tree / "examplesvc/uv.lock").read_text() == "old lock\n"  # 依頼の tree は書き換えない


def test_process_drops_the_package_that_cannot_be_upgraded(tree, tmp_path):
    uv = FakeUv(fail={"b"})
    r = process(job_of("a", "b", "c"), tree, uv, tmp_path)
    assert (r.ok, r.lock, r.applied) == (True, "a==9.9 c==9.9", ("a", "c"))
    assert [n for n, _ in r.failed] == ["b"] and "No solution" in r.failed[0][1]
    assert len(uv.calls) == 5  # まとめて 1 + 1 つずつ 3 + 通ったものだけで 1


def test_process_reports_when_nothing_can_be_upgraded(tree, tmp_path):
    r = process(job_of("a"), tree, FakeUv(fail={"a"}), tmp_path)
    assert (r.ok, r.lock, [n for n, _ in r.failed]) == (False, None, ["a"])
    r = process(job_of("a", "b"), tree, FakeUv(conflict=True), tmp_path)
    assert not r.ok and [n for n, _ in r.failed] == ["a", "b"]


def test_run_pending_writes_results_once(snapshot, tmp_path):
    in_dir, out_dir = tmp_path / "in", tmp_path / "out"
    out_dir.mkdir()
    jobs.write_job(in_dir, UpdateJob(RUN, "examplesvc", (("examplelib", "1.4.0"),)), snapshot)
    (in_dir / "rem_ffffffffffffffff.json").write_text("{broken")
    uv = FakeUv()
    assert run_pending(in_dir, out_dir, uv, tmp_path, "uv 0.13.5") == 2
    r = jobs.read_result(out_dir, RUN)
    assert r is not None and r.ok and r.lock == "examplelib==1.4.0" and r.uv_version == "uv 0.13.5"
    broken = jobs.read_result(out_dir, "rem_ffffffffffffffff")
    assert broken is not None and not broken.ok and broken.error
    assert run_pending(in_dir, out_dir, uv, tmp_path) == 0  # 結果があるものはやり直さない
    assert len(uv.calls) == 1


def test_result_round_trip(tmp_path):
    r = UpdateResult(RUN, True, "lock", ("a",), (("b", "boom"),), "uv 0.13.5", "2026-11-08T00:00:00Z")
    jobs.write_result(tmp_path, r)
    assert jobs.read_result(tmp_path, RUN) == r


# ── egress ────────────────────────────────────────────────────────────────
ALLOW = frozenset({"pypi.org", "files.pythonhosted.org"})


@pytest.mark.parametrize(("line", "verdict"), [
    ("CONNECT pypi.org:443 HTTP/1.1", ("pypi.org", 443)),
    ("CONNECT FILES.pythonhosted.org.:443 HTTP/1.1", ("files.pythonhosted.org", 443)),
    ("CONNECT pypi.org:80 HTTP/1.1", "port 80 is not allowed"),
    ("CONNECT evil.example:443 HTTP/1.1", "host evil.example is not allowed"),
    ("CONNECT pypi.org.evil.example:443 HTTP/1.1", "host pypi.org.evil.example is not allowed"),
    ("GET http://pypi.org/simple HTTP/1.1", "only CONNECT is allowed"),
    ("CONNECT 169.254.169.254:443 HTTP/1.1", "host 169.254.169.254 is not allowed"),
])
def test_egress_decide(line, verdict):
    assert egress.decide(line, ALLOW) == verdict


def test_parse_allow_defaults():
    assert egress.parse_allow("") == frozenset(egress.DEFAULT_ALLOW)
    assert egress.parse_allow(" PyPI.org , ") == frozenset({"pypi.org"})


def test_egress_tunnels_only_allowed_hosts():
    async def scenario() -> tuple[bytes, bytes, bytes]:
        async def echo(reader, writer):
            data = await reader.read(100)
            writer.write(b"echo:" + data)
            await writer.drain()
            writer.close()

        upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
        up_port = upstream.sockets[0].getsockname()[1]
        proxy = await egress.start("127.0.0.1", 0, frozenset({"localhost"}), frozenset({up_port}))
        port = proxy.sockets[0].getsockname()[1]

        async def ask(target: str, payload: bytes = b"") -> bytes:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode() + payload)
            await writer.drain()
            data = await asyncio.wait_for(reader.read(1000), 5)
            if b" 200 " in data and payload:
                data += await asyncio.wait_for(reader.read(1000), 5)
            writer.close()
            return data

        ok = await ask(f"localhost:{up_port}", b"hello")
        denied_host = await ask(f"evil.example:{up_port}")
        denied_port = await ask("localhost:1")
        proxy.close()
        upstream.close()
        return ok, denied_host, denied_port

    ok, denied_host, denied_port = asyncio.run(scenario())
    assert ok.startswith(b"HTTP/1.1 200") and ok.endswith(b"echo:hello")
    assert denied_host.startswith(b"HTTP/1.1 403")
    assert denied_port.startswith(b"HTTP/1.1 403")


def test_compose_isolates_the_updater():
    """updater にはトークン・DB・作業コピーを渡さず、外へは egress 経由でしか出られない。"""
    from pathlib import Path

    import yaml

    compose = yaml.safe_load((Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text())
    services, networks = compose["services"], compose["networks"]
    up = services["remediation-updater"]
    assert "env_file" not in up
    assert up["networks"] == ["updater"] and networks["updater"]["internal"] is True
    assert up["read_only"] is True and up["cap_drop"] == ["ALL"]
    assert sorted(up["volumes"]) == ["./data/remediation/jobs/in:/app/data/remediation/jobs/in:ro",
                                     "./data/remediation/jobs/out:/app/data/remediation/jobs/out"]
    assert up["environment"]["HTTPS_PROXY"] == "http://remediation-egress:3128"
    eg = services["remediation-egress"]
    assert eg["volumes"] == [] and eg["env_file"] == [] and set(eg["networks"]) == {"updater", "default"}
    # トークンを持つのは remediation だけ
    holders = [name for name, svc in services.items()
               if any("remediation.env" in str(e) for e in svc.get("env_file") or [])]
    assert holders == ["remediation"]
