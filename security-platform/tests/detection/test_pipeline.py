"""A2 照合ジョブの結合テスト (intel.db は A1 のパイプラインに偽の OSV を流して作る)。"""
from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import text

from src.common.db import make_engine
from src.common.services import Service
from src.detection.pipeline import DetectionPipeline
from tests.intel.test_pipeline import MAL, PYSEC, ghsa
from tests.intel.test_pipeline import env as intel_env  # noqa: F401  (fixture)


def uv_lock(**pins: str) -> str:
    deps = ", ".join(f'{{ name = "{n}" }}' for n in pins)
    out = f'version = 1\n\n[[package]]\nname = "app"\nversion = "0.1.0"\nsource = {{ editable = "." }}\n' \
          f"dependencies = [{deps}]\n"
    for name, version in pins.items():
        out += f'\n[[package]]\nname = "{name}"\nversion = "{version}"\n' \
               'source = { registry = "https://pypi.org/simple" }\n'
    return out


def package_lock(**pins: str) -> str:
    pkgs: dict[str, Any] = {"": {"name": "front", "dependencies": dict.fromkeys(pins, "*")}}
    pkgs.update({f"node_modules/{n}": {"version": v} for n, v in pins.items()})
    return json.dumps({"lockfileVersion": 3, "packages": pkgs})


@pytest.fixture
def setup(intel_env, tmp_path):  # noqa: F811
    intel, osv, _, paths = intel_env
    osv.zips["npm"].append(MAL | {"affected": [
        {"package": {"ecosystem": "npm", "name": "evilpkg"}, "versions": ["1.0.0"]}]})
    intel.bootstrap()  # CVE-2026-1111 (examplelib < 2.4.3, CRITICAL, KEV) と MAL-2026-100 (evilpkg 1.0.0)
    repo = tmp_path / "repo"
    (repo / "api").mkdir(parents=True)
    (repo / "front").mkdir()
    (repo / "api/uv.lock").write_text(uv_lock(ExampleLib="2.4.0", other="1.0"))
    (repo / "front/package-lock.json").write_text(package_lock(evilpkg="1.0.0", leftish="2.0.0"))
    services = [
        Service(id="api", path="api/", exposure="external", deployed=True, lockfiles=("uv.lock",)),
        Service(id="front", path="front/", exposure="none", deployed=False, lockfiles=("package-lock.json",)),
    ]

    def make() -> DetectionPipeline:
        return DetectionPipeline(
            make_engine(paths.sqlite_path("detection")),
            make_engine(paths.sqlite_path("intel"), read_only=True),
            paths, repo, services,
        )

    return make, repo, osv, intel


def q(p: DetectionPipeline, sql: str) -> list[tuple]:
    with p.engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql)).all()]


def events(p: DetectionPipeline) -> list[tuple[str, dict]]:
    return [(t, json.loads(b)) for t, b in q(p, "SELECT type, payload FROM events ORDER BY seq")]


def test_scan_opens_findings_with_priority(setup):
    make, *_ = setup
    p = make()
    r = p.run_scan()
    assert (r.services, r.components, r.opened) == (2, 4, 2)
    rows = {r[0]: r[1:] for r in q(p, "SELECT advisory_id, service_id, purl, priority, fixed_version, "
                                      "dependency_path, state FROM findings")}
    assert rows == {
        "CVE-2026-1111": ("api", "pkg:pypi/examplelib@2.4.0", "P1", "2.4.3", "direct", "open"),
        "MAL-2026-100": ("front", "pkg:npm/evilpkg@1.0.0", "P1", None, "direct", "open"),
    }
    assert sorted(t for t, _ in events(p)) == ["finding.opened", "finding.opened"]
    assert q(p, "SELECT count(*) FROM sboms WHERE is_current") == [(2,)]
    assert q(p, "SELECT status FROM scan_runs") == [("success",)]


def test_rescan_is_idempotent_then_resolves_and_reopens(setup):
    make, repo, *_ = setup
    p = make()
    p.run_scan()
    again = p.run_scan()
    assert (again.opened, again.updated, again.resolved) == (0, 0, 0)

    (repo / "api/uv.lock").write_text(uv_lock(ExampleLib="2.4.3", other="1.0"))
    fixed = p.run_scan()
    assert (fixed.resolved, fixed.open_findings) == (1, 1)
    assert q(p, "SELECT state FROM findings WHERE service_id = 'api'") == [("resolved",)]

    (repo / "api/uv.lock").write_text(uv_lock(ExampleLib="2.4.0", other="1.0"))
    assert p.run_scan().opened == 1
    assert [t for t, _ in events(p)][-2:] == ["finding.resolved", "finding.reopened"]
    assert q(p, "SELECT from_state, to_state FROM finding_transitions WHERE finding_id IN "
                "(SELECT finding_id FROM findings WHERE service_id = 'api') ORDER BY id") == [
        (None, "open"), ("open", "resolved"), ("resolved", "open"),
    ]


def test_missing_lockfile_keeps_findings_open(setup):
    make, repo, *_ = setup
    p = make()
    p.run_scan()
    (repo / "api/uv.lock").unlink()
    r = p.run_scan()
    assert r.resolved == 0 and r.warnings == ["api: api/uv.lock がありません"]
    assert q(p, "SELECT state FROM findings WHERE service_id = 'api'") == [("open",)]


def test_priority_drops_when_kev_removed(setup):
    """KEV から外れると P1 → P2 (Critical) に下がり、finding.updated を出す。"""
    make, _, _, intel = setup
    p = make()
    p.run_scan()
    with intel.engine.begin() as conn:
        conn.execute(text("DELETE FROM kev_entries WHERE cve = 'CVE-2026-1111'"))
    r = p.run_scan()
    assert r.updated == 1
    kind, payload = events(p)[-1]
    assert kind == "finding.updated"
    assert (payload["previous_priority"], payload["priority"]) == ("P1", "P2")


def test_withdrawn_advisory_resolves_finding(setup):
    make, _, osv, intel = setup
    p = make()
    p.run_scan()
    gone = {"withdrawn": "2026-10-21T00:00:00Z", "modified": "2026-10-21T00:00:00Z"}
    osv.zips["PyPI"] = [ghsa() | gone, PYSEC | gone]
    intel.run_osv_full()
    assert p.run_scan().resolved == 1
    assert q(p, "SELECT state FROM findings WHERE advisory_id = 'CVE-2026-1111'") == [("resolved",)]
