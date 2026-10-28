"""A2 照合ジョブの結合テスト (intel.db は A1 のパイプラインに偽の OSV を流して作る)。"""
from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import text

from src.common.timeutil import utc_now_iso

from src.common.db import make_engine
from src.common.services import ImageRef, Service
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


HIGH = [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H"}]
CRITICAL = [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}]


def osv_rec(rec_id: str, cve: str, eco: str, name: str, events: list[dict[str, str]], severity: list) -> dict:
    return {"id": rec_id, "modified": "2026-10-01T00:00:00Z", "aliases": [cve], "severity": severity,
            "affected": [{"package": {"ecosystem": eco, "name": name},
                          "ranges": [{"type": "SEMVER" if eco == "Bitnami" else "ECOSYSTEM", "events": events}]}]}


DEB_OPENSSL = osv_rec("DEBIAN-CVE-2026-3001", "CVE-2026-3001", "Debian:12", "openssl",
                      [{"introduced": "0"}, {"fixed": "3.0.22-1~deb12u2"}], HIGH)
DEB_CURL = osv_rec("DEBIAN-CVE-2026-3002", "CVE-2026-3002", "Debian:12", "curl", [{"introduced": "0"}], CRITICAL)
BIT_NODE = osv_rec("BIT-node-2026-4001", "CVE-2026-4001", "Bitnami", "node",
                   [{"introduced": "0"}, {"fixed": "24.20.0"}], HIGH)
DIGEST = "sha256:" + "d" * 64
IMAGE_REFS = (ImageRef(cloud_run="web"), ImageRef(cloud_run_job="web-batch"))


def image_sbom(paths, service_id: str, *purls: str, refs=IMAGE_REFS, generated_at: str | None = None) -> None:
    """make detection-images が置くのと同じ形で SBOM とマニフェストを書く。"""
    d = paths.sbom_images_dir
    (d / "blobs").mkdir(parents=True, exist_ok=True)
    comps = [{"type": "library", "name": "x", "purl": p} for p in purls]
    comps.append({"type": "operating-system", "name": "debian", "version": "12.15"})
    (d / "blobs" / f"{DIGEST.replace(':', '-')}.cdx.json").write_text(
        json.dumps({"bomFormat": "CycloneDX", "components": comps}))
    images = [{"ref": r.key, "image": "registry.test/app/web:abc", "digest": DIGEST,
               "sbom": f"{DIGEST.replace(':', '-')}.cdx.json"} for r in refs]
    (d / f"{service_id}.json").write_text(json.dumps({
        "service_id": service_id, "generated_at": generated_at or utc_now_iso(), "images": images}))


@pytest.fixture
def setup(intel_env, tmp_path):  # noqa: F811
    intel, osv, _, paths = intel_env
    osv.zips["npm"].append(MAL | {"affected": [
        {"package": {"ecosystem": "npm", "name": "evilpkg"}, "versions": ["1.0.0"]}]})
    osv.zips["Debian"] += [DEB_OPENSSL, DEB_CURL]
    osv.zips["Bitnami"] = [BIT_NODE]
    # CVE-2026-1111 (examplelib < 2.4.3, CRITICAL, KEV) と MAL-2026-100 (evilpkg 1.0.0)
    # イメージ用: CVE-2026-3001 (Debian openssl, HIGH, 修正あり)・CVE-2026-3002 (Debian curl, CRITICAL, 未修正)・
    # CVE-2026-4001 (Bitnami node < 24.20.0, HIGH)
    intel.bootstrap()
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


@pytest.fixture
def image_setup(intel_env, setup):  # noqa: F811
    """api の lockfile に加えて、本番イメージを持つ web サービスを照合する。"""
    _, repo, osv, intel = setup
    paths = intel_env[3]
    (repo / "web").mkdir()
    services = [
        Service(id="api", path="api/", exposure="external", deployed=True, lockfiles=("uv.lock",),
                images=(ImageRef(cloud_run="api"),)),
        Service(id="web", path="web/", exposure="external", deployed=True, images=IMAGE_REFS),
    ]

    def make() -> DetectionPipeline:
        return DetectionPipeline(
            make_engine(paths.sqlite_path("detection")),
            make_engine(paths.sqlite_path("intel"), read_only=True),
            paths, repo, services,
        )

    return make, paths


WEB_PURLS = (
    "pkg:deb/debian/libssl3@3.0.22-1~deb12u1?distro=debian-12.15&upstream=openssl",
    "pkg:deb/debian/curl@7.88.1-10%2Bdeb12u15?distro=debian-12.15",
    "pkg:deb/debian/nodejs@24.19.0-1nodesource1?distro=debian-12.15",
    "pkg:pypi/examplelib@2.4.0",
)


def test_image_sbom_findings(image_setup):
    make, paths = image_setup
    image_sbom(paths, "web", *WEB_PURLS)
    p = make()
    r = p.run_scan()
    assert r.incomplete == {"api"}  # api は images を書いたのに SBOM が無い
    assert "api: 本番イメージの SBOM がありません (make detection-images)" in r.warnings
    rows = {(r[0], r[1]): r[2:] for r in q(p, """
        SELECT advisory_id, purl, priority, fixed_version, dependency_path,
               json_extract(evidence_json, '$.source_kind'), json_extract(evidence_json, '$.reasons')
        FROM findings WHERE service_id = 'web'""")}
    assert rows == {
        ("CVE-2026-3001", "pkg:deb/debian/openssl@3.0.22-1~deb12u1?distro=debian-12"):
            ("P3", "3.0.22-1~deb12u2", "transitive", "image", '["深刻度 High"]'),
        ("CVE-2026-3002", "pkg:deb/debian/curl@7.88.1-10%2Bdeb12u15?distro=debian-12"):
            ("P4", None, "transitive", "image", '["深刻度 Critical","Debian で未修正 (P4 に下げる)"]'),
        ("CVE-2026-4001", "pkg:generic/node@24.19.0"):
            ("P3", "24.20.0", "transitive", "image", '["深刻度 High"]'),
        ("CVE-2026-1111", "pkg:pypi/examplelib@2.4.0"):
            ("P1", "2.4.3", "transitive", "image", '["KEV 掲載 (悪用を確認)"]'),
    }
    assert q(p, "SELECT kind, subject, path, is_current FROM sboms WHERE service_id = 'web'") == [
        ("image", DIGEST, f"image:registry.test/app/web@{DIGEST}", 1)]


def test_lockfile_and_image_merge_into_one_finding(image_setup):
    """同じパッケージが lockfile と本番イメージの両方にあれば 1 件 (lockfile の direct を残す)。"""
    make, paths = image_setup
    image_sbom(paths, "web", *WEB_PURLS)
    image_sbom(paths, "api", "pkg:pypi/examplelib@2.4.0", refs=(ImageRef(cloud_run="api"),))
    p = make()
    r = p.run_scan()
    assert r.incomplete == set()
    assert q(p, "SELECT dependency_path, json_extract(evidence_json, '$.source_kind') FROM findings "
                "WHERE service_id = 'api'") == [("direct", "source")]


def test_missing_or_stale_image_sbom(image_setup):
    make, paths = image_setup
    image_sbom(paths, "web", *WEB_PURLS)
    p = make()
    p.run_scan()
    image_sbom(paths, "web", *WEB_PURLS, refs=IMAGE_REFS[:1], generated_at="2026-01-01T00:00:00Z")
    r = p.run_scan()
    assert "web: SBOM の無いイメージがあります: cloud_run_job:web-batch (make detection-images)" in r.warnings
    assert "web: 本番イメージの SBOM が古くなっています (make detection-images)" in r.warnings
    assert r.resolved == 0  # 欠けているので閉じない
    (paths.sbom_images_dir / "web.json").unlink()
    assert make().run_scan().resolved == 0
    assert q(p, "SELECT count(*) FROM findings WHERE service_id = 'web' AND state = 'open'") == [(4,)]


def test_broken_manifest_does_not_stop_scan(image_setup):
    make, paths = image_setup
    image_sbom(paths, "web", *WEB_PURLS)
    manifest = paths.sbom_images_dir / "web.json"
    data = json.loads(manifest.read_text())
    data["generated_at"] = "yesterday"
    data["images"][1]["digest"] = "../../intel.db"
    manifest.write_text(json.dumps(data))
    r = make().run_scan()
    assert "web: マニフェストのダイジェストが不正です (cloud_run_job:web-batch)" in r.warnings
    assert "web: 本番イメージの SBOM が古くなっています (make detection-images)" in r.warnings
    assert r.opened == 5  # 正しい方のイメージは照合する (api の lockfile 1 件 + web 4 件)


# ── 例外 (誤検知・リスク受容) ───────────────────────────────────────────────

def test_exception_suppresses_then_revoke_reopens(setup):
    from src.detection.exceptions import ExceptionStore

    make, *_ = setup
    p = make()
    p.run_scan()
    store = ExceptionStore(p.engine)
    exc = store.add("*", "CVE-2026-1111", "ExampleLib", "false_positive", "使っていない関数の脆弱性", None)
    r = p.run_scan()
    assert (r.suppressed, r.open_findings) == (1, 1)
    assert q(p, "SELECT state, due_at, json_extract(evidence_json, '$.exception_id') FROM findings "
                "WHERE advisory_id = 'CVE-2026-1111'") == [("suppressed", None, exc.exception_id)]
    assert events(p)[-1][0] == "finding.suppressed"
    assert p.run_scan().suppressed == 0  # 抑止したままなら何も起きない

    assert store.revoke(exc.exception_id) and not store.revoke(exc.exception_id)
    r = p.run_scan()
    assert r.opened == 1
    kind, payload = events(p)[-1]
    assert (kind, payload["priority"]) == ("finding.reopened", "P1")
    assert q(p, "SELECT state, due_at IS NOT NULL FROM findings WHERE advisory_id = 'CVE-2026-1111'") == [
        ("open", 1)]
    assert q(p, "SELECT from_state, to_state FROM finding_transitions ORDER BY id")[-2:] == [
        ("open", "suppressed"), ("suppressed", "open")]


def test_exception_scope_and_expiry(setup):
    from datetime import timedelta

    from src.common.timeutil import utc_now
    from src.detection.exceptions import ExceptionStore

    make, repo, *_ = setup
    p = make()
    p.run_scan()  # 初回にスキーマを作る
    store = ExceptionStore(p.engine)
    store.add("front", "CVE-2026-1111", None, "false_positive", "別サービス向け", None)  # 当たらない
    store.add("api", "CVE-2026-1111", "otherpkg", "false_positive", "別パッケージ向け", None)  # 当たらない
    past = utc_now() - timedelta(days=30)
    store.add("api", "CVE-2026-1111", None, "risk_accepted", "期限切れ", past + timedelta(days=1), now=past)
    assert p.run_scan().suppressed == 0
    store.add("api", "CVE-2026-1111", None, "risk_accepted", "次の更新まで", utc_now() + timedelta(days=7))
    assert p.run_scan().suppressed == 1
    # 抑止中に更新されて該当しなくなれば resolved
    (repo / "api/uv.lock").write_text(uv_lock(ExampleLib="2.4.3", other="1.0"))
    assert p.run_scan().resolved == 1
    assert q(p, "SELECT state FROM findings WHERE advisory_id = 'CVE-2026-1111'") == [("resolved",)]


def test_exception_validation():
    from datetime import timedelta

    from src.common.timeutil import utc_now
    from src.detection.exceptions import validate

    now = utc_now()
    for kind, reason, expires in [
        ("ignore", "x", None),                                   # 未知の種類
        ("false_positive", " ", None),                           # 理由なし
        ("risk_accepted", "x", None),                            # 期限なし
        ("risk_accepted", "x", now + timedelta(days=181)),       # 期限が長すぎる
        ("false_positive", "x", now - timedelta(days=1)),        # 期限が過去
    ]:
        with pytest.raises(ValueError):
            validate(kind, reason, expires, now)
    validate("risk_accepted", "x", now + timedelta(days=180), now)
