"""A1 パイプラインの結合テスト (ネットワークなし。OSV・KEV・EPSS は偽物を差し込む)。"""
from __future__ import annotations

import copy
import gzip
import io
import json
import zipfile
from typing import Any

import pytest
from sqlalchemy import text

from src.common.db import make_engine
from src.common.migrate import upgrade_all
from src.common.paths import DataPaths
from src.common.raw_store import RawStore
from src.common.timeutil import parse_iso
from src.intel import changes as changes_mod
from src.intel.pipeline import IntelPipeline
from src.intel.sources.osv import MalformedRecord, ModifiedEntry

KEV_URL = "https://kev.test/kev.json"
EPSS_URL = "https://epss.test/epss.csv.gz"


def ghsa(fixed: str = "2.4.3", withdrawn: str | None = None) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": "GHSA-aaaa-bbbb-cccc",
        "modified": "2026-10-01T00:00:00Z",
        "published": "2026-09-01T00:00:00Z",
        "aliases": ["CVE-2026-1111"],
        "summary": "RCE in examplelib",
        "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
        "affected": [{
            "package": {"ecosystem": "PyPI", "name": "examplelib", "purl": "pkg:pypi/examplelib"},
            "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": fixed}]}],
        }],
    }
    if withdrawn:
        rec["withdrawn"] = withdrawn
    return rec


PYSEC = {
    "id": "PYSEC-2026-1", "modified": "2026-08-01T00:00:00Z", "published": "2026-08-15T00:00:00Z",
    "aliases": ["CVE-2026-1111", "GHSA-aaaa-bbbb-cccc"],
    "affected": [{"package": {"ecosystem": "PyPI", "name": "examplelib"},
                  "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.4.3"}]}]}],
}
NPM_NO_CVE = {
    "id": "GHSA-nnnn-nnnn-nnnn", "modified": "2026-10-01T00:00:00Z",
    "affected": [{"package": {"ecosystem": "npm", "name": "leftish"}, "ranges": []}],
}
DSA_BUNDLE = {
    "id": "DSA-5999-1", "modified": "2026-10-01T00:00:00Z",
    "upstream": ["CVE-2026-2001", "CVE-2026-2002"],
    "affected": [{"package": {"ecosystem": "Debian:12", "name": "openssl"}, "ranges": []}],
}


class FakeOsv:
    def __init__(self) -> None:
        self.zips: dict[str, list[dict[str, Any]]] = {
            "PyPI": [ghsa(), PYSEC], "npm": [NPM_NO_CVE], "Debian": [DSA_BUNDLE],
        }
        self.records: dict[str, dict[str, Any] | MalformedRecord] = {}
        self.modified: list[ModifiedEntry] = []
        self.head = "2026-10-20T00:00:00.000000001Z"
        self.fail_on: str | None = None
        self.downloaded: list[str] = []

    def list_ecosystems(self) -> list[str]:
        return list(self.zips)

    def latest_modified(self) -> str:
        return self.head

    def modified_since(self, cursor: str) -> list[ModifiedEntry]:
        since = parse_iso(cursor)
        return [e for e in self.modified if parse_iso(e.modified) >= since]

    def fetch_record(self, ecosystem: str, record_id: str) -> dict[str, Any] | None:
        rec = self.records.get(record_id)
        if isinstance(rec, MalformedRecord):
            raise rec
        return copy.deepcopy(rec)

    def download_all_zip(self, ecosystem: str, store: RawStore, name: str):
        if ecosystem == self.fail_on:
            raise RuntimeError(f"download failed: {ecosystem}")
        self.downloaded.append(ecosystem)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for rec in self.zips[ecosystem]:
                zf.writestr(f"{rec['id']}.json", json.dumps(rec))
        with store.open_new("osv", name) as (f, path):
            f.write(buf.getvalue())
        return path


def kev_body(*cves: str) -> bytes:
    return json.dumps({"vulnerabilities": [
        {"cveID": c, "vendorProject": "v", "product": "p", "vulnerabilityName": f"{c} vuln",
         "dateAdded": "2026-10-10"} for c in cves
    ]}).encode()


def epss_body(rows: dict[str, float], day: str = "2026-10-23", model: str = "v2025.03.14") -> bytes:
    lines = [f"#model_version:{model},score_date:{day}T00:00:00Z", "cve,epss,percentile"]
    lines += [f"{c},{s},0.9" for c, s in rows.items()]
    return gzip.compress("\n".join(lines).encode())


@pytest.fixture
def env(tmp_path):
    paths = DataPaths(tmp_path / "data")
    upgrade_all(paths)
    osv = FakeOsv()
    remote = {KEV_URL: kev_body("CVE-2026-1111", "CVE-2026-9999"),
              EPSS_URL: epss_body({"CVE-2026-1111": 0.2, "CVE-2026-2001": 0.05})}
    pipeline = IntelPipeline(
        make_engine(paths.sqlite_path("intel")), paths, osv, remote.__getitem__,
        kev_url=KEV_URL, epss_url=EPSS_URL, epss_delta=0.1,
        incremental_max_per_ecosystem=2, full_snapshots_kept=2,
    )
    return pipeline, osv, remote, paths


def q(pipeline: IntelPipeline, sql: str, **params: Any) -> list[tuple]:
    with pipeline.engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql), params).all()]


def events(pipeline: IntelPipeline, type_: str = "advisory.changed") -> list[dict[str, Any]]:
    rows = q(pipeline, "SELECT payload FROM events WHERE type = :t ORDER BY seq", t=type_)
    return [json.loads(r[0]) for r in rows]


def test_bootstrap_builds_advisories_without_change_events(env):
    pipeline, osv, _, paths = env
    assert pipeline.bootstrap() is True
    advisories = dict(q(pipeline, "SELECT advisory_id, record_count FROM advisories"))
    assert advisories == {
        "CVE-2026-1111": 2,           # GHSA と PYSEC が CVE で合流
        "GHSA-nnnn-nnnn-nnnn": 1,     # CVE なし
        "DSA-5999-1": 1,              # まとめ告知は独立
        "CVE-2026-9999": 0,           # KEV だけに載っている
    }
    view = {r[0]: r[1:] for r in q(pipeline, "SELECT advisory_id, kev, epss, severity FROM v_advisories")}
    assert view["CVE-2026-1111"] == (1, 0.2, "CRITICAL")
    assert view["DSA-5999-1"] == (0, 0.05, None)  # 含む CVE の EPSS を引く
    assert events(pipeline) == []
    assert len(events(pipeline, "advisory.bootstrap_completed")) == 1
    assert pipeline.osv_cursor() == osv.head
    assert (paths.osv_db_dir / "osv-scanner/PyPI/all.zip").exists()
    assert pipeline.bootstrap() is False


MAL = {
    "id": "MAL-2026-100", "modified": "2026-10-01T00:00:00Z",
    "summary": "Malicious code in evilpkg (npm)",
    "affected": [{"package": {"ecosystem": "npm", "name": "evilpkg"}, "ranges": []}],
}
ALSA = {
    "id": "ALSA-2026:A014", "modified": "2026-10-01T00:00:00Z",
    "summary": "Important: php:8.1 security update",
    "affected": [{"package": {"ecosystem": "AlmaLinux:9", "name": "php"}, "ranges": []}],
}


def _bootstrap_with_mal_and_alsa(env):
    pipeline, osv, _, _ = env
    osv.zips["npm"].append(MAL)
    osv.zips["AlmaLinux"] = [ALSA]
    assert pipeline.bootstrap() is True
    return pipeline


def test_malicious_kind_and_summary_severity(env):
    pipeline = _bootstrap_with_mal_and_alsa(env)
    rows = dict(q(pipeline, "SELECT advisory_id, kind || '/' || coalesce(severity, '-') FROM advisories "
                            "WHERE advisory_id IN ('MAL-2026-100', 'ALSA-2026:A014', 'CVE-2026-1111')"))
    assert rows == {
        "MAL-2026-100": "malicious/-",
        "ALSA-2026:A014": "vulnerability/HIGH",
        "CVE-2026-1111": "vulnerability/CRITICAL",
    }


def test_migration_0002_backfills_existing_rows(env):
    """0001 時点で取り込んだデータ (kind 未分類・summary の深刻度なし) を 0002 が補正する。"""
    from alembic import command

    from src.common.migrate import alembic_config, upgrade

    pipeline = _bootstrap_with_mal_and_alsa(env)
    paths = env[3]
    command.downgrade(alembic_config("intel", paths), "0001")
    with pipeline.engine.begin() as conn:
        conn.execute(text("UPDATE osv_records SET severity_label = NULL WHERE record_id = 'ALSA-2026:A014'"))
        conn.execute(text("UPDATE advisories SET severity = NULL WHERE advisory_id = 'ALSA-2026:A014'"))
    assert q(pipeline, "SELECT count(*) FROM advisories WHERE kind = 'malicious'") == [(0,)]

    upgrade("intel", paths)
    assert q(pipeline, "SELECT kind FROM advisories WHERE advisory_id = 'MAL-2026-100'") == [("malicious",)]
    assert q(pipeline, "SELECT severity_label FROM osv_records WHERE record_id = 'ALSA-2026:A014'") == [("HIGH",)]
    assert q(pipeline, "SELECT advisory_id FROM advisories_dirty") == [("ALSA-2026:A014",)]


def test_bootstrap_resumes_after_failure(env):
    pipeline, osv, _, _ = env
    osv.fail_on = "Debian"
    with pytest.raises(RuntimeError):
        pipeline.bootstrap()
    assert q(pipeline, "SELECT status FROM source_runs WHERE source = 'osv_full'") == [("failed",)]
    osv.fail_on = None
    osv.downloaded.clear()
    assert pipeline.bootstrap() is True
    assert osv.downloaded == ["Debian"]


def test_incremental_emits_one_event_per_change(env):
    pipeline, osv, _, _ = env
    pipeline.bootstrap()
    updated = ghsa(fixed="2.4.4") | {"modified": "2026-10-21T00:00:00Z"}
    new = {"id": "GHSA-new0-new0-new0", "modified": "2026-10-21T00:00:00Z", "aliases": ["CVE-2026-3333"],
           "affected": [{"package": {"ecosystem": "PyPI", "name": "other", "purl": "pkg:pypi/other"},
                         "ranges": []}]}
    osv.records = {updated["id"]: updated, new["id"]: new}
    osv.modified = [ModifiedEntry("2026-10-21T00:00:00.5Z", "PyPI", new["id"]),
                    ModifiedEntry("2026-10-21T00:00:00.1Z", "PyPI", updated["id"])]
    pipeline.run_osv_incremental()
    got = {e["advisory_id"]: e for e in events(pipeline)}
    assert got["CVE-2026-1111"]["change_types"] == ["fixed_version_published", "affected_changed"]
    assert got["CVE-2026-1111"]["affected_purls"] == ["PyPI:examplelib", "pkg:pypi/examplelib"]
    assert got["CVE-2026-1111"]["current"]["kev"] is True
    assert got["CVE-2026-3333"]["change_types"] == ["created"]
    assert pipeline.osv_cursor() == "2026-10-21T00:00:00.5Z"
    assert q(pipeline, "SELECT COUNT(*) FROM advisory_history")[0][0] == 2


def test_unchanged_records_are_skipped(env):
    pipeline, osv, _, _ = env
    pipeline.bootstrap()
    osv.records = {"GHSA-aaaa-bbbb-cccc": ghsa()}
    osv.modified = [ModifiedEntry("2026-10-21T00:00:00Z", "PyPI", "GHSA-aaaa-bbbb-cccc")]
    pipeline.run_osv_incremental()
    assert events(pipeline) == []


def test_withdrawn_and_bulk_fallback(env):
    pipeline, osv, _, _ = env
    pipeline.bootstrap()
    osv.zips["PyPI"] = [ghsa(withdrawn="2026-10-21T00:00:00Z") | {"modified": "2026-10-21T00:00:00Z"},
                        PYSEC | {"withdrawn": "2026-10-21T00:00:00Z", "modified": "2026-10-21T00:00:00Z"}]
    osv.modified = [ModifiedEntry(f"2026-10-21T00:00:0{i}Z", "PyPI", f"X-{i}") for i in range(3)]
    osv.downloaded.clear()
    pipeline.run_osv_incremental()  # 3 件 > 上限 2 件なので PyPI は全量取得に切り替わる
    assert osv.downloaded == ["PyPI"]
    (event,) = events(pipeline)
    assert event["advisory_id"] == "CVE-2026-1111" and "withdrawn" in event["change_types"]


def test_cveless_record_merges_when_alias_gains_cve(env):
    pipeline, osv, _, _ = env
    osv.zips = {"PyPI": [{"id": "PYSEC-2026-7", "modified": "2026-10-01T00:00:00Z",
                          "aliases": ["GHSA-late-late-late"]}]}
    pipeline.bootstrap()
    assert q(pipeline, "SELECT advisory_id FROM osv_records") == [("PYSEC-2026-7",)]
    late = {"id": "GHSA-late-late-late", "modified": "2026-10-21T00:00:00Z",
            "aliases": ["CVE-2026-4444", "PYSEC-2026-7"]}
    osv.records = {late["id"]: late}
    osv.modified = [ModifiedEntry("2026-10-21T00:00:00Z", "PyPI", late["id"])]
    pipeline.run_osv_incremental()
    assert set(q(pipeline, "SELECT advisory_id FROM osv_records")) == {("CVE-2026-4444",)}
    got = {e["advisory_id"]: e["change_types"] for e in events(pipeline)}
    assert got == {"CVE-2026-4444": ["created"], "PYSEC-2026-7": ["removed"]}


def test_kev_and_epss_signals_after_bootstrap(env):
    pipeline, _, remote, _ = env
    pipeline.bootstrap()
    remote[KEV_URL] = kev_body("CVE-2026-1111", "CVE-2026-9999", "CVE-2026-2002")
    pipeline.run_kev()
    remote[EPSS_URL] = epss_body({"CVE-2026-1111": 0.25, "CVE-2026-2001": 0.6}, day="2026-10-24")
    pipeline.run_epss()
    got = [(e["advisory_id"], e["change_types"]) for e in events(pipeline)]
    assert got == [("DSA-5999-1", ["kev_added"]), ("DSA-5999-1", ["epss_increased"])]
    assert q(pipeline, "SELECT epss FROM epss_scores WHERE cve = 'CVE-2026-1111'") == [(0.25,)]


def test_kev_removal_drops_kev_only_advisory(env):
    pipeline, _, remote, _ = env
    pipeline.bootstrap()
    remote[KEV_URL] = kev_body("CVE-2026-1111")
    pipeline.run_kev()
    assert q(pipeline, "SELECT 1 FROM advisories WHERE advisory_id = 'CVE-2026-9999'") == []
    got = [(e["advisory_id"], e["change_types"]) for e in events(pipeline)]
    assert got == [("CVE-2026-9999", ["removed", "kev_removed"])]


def test_incremental_requires_bootstrap(env):
    pipeline, *_ = env
    with pytest.raises(RuntimeError, match="bootstrap"):
        pipeline.run_osv_incremental()


def test_last_success(env):
    pipeline, *_ = env
    assert pipeline.last_success("kev") is None
    pipeline.run_kev()
    assert pipeline.last_success("kev") is not None


# ── レビュー指摘の回帰テスト ─────────────────────────────────────────────


def test_rollup_crash_is_recovered_on_next_run(env, monkeypatch):
    """レコード書き込み後・再集計前に落ちても、次の実行で再集計とイベントが出る。"""
    pipeline, osv, _, _ = env
    pipeline.bootstrap()
    updated = ghsa(fixed="2.4.4") | {"modified": "2026-10-21T00:00:00Z"}
    osv.records = {updated["id"]: updated}
    osv.modified = [ModifiedEntry("2026-10-21T00:00:00Z", "PyPI", updated["id"])]
    real = changes_mod.apply
    monkeypatch.setattr(changes_mod, "apply", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        pipeline.run_osv_incremental()
    assert q(pipeline, "SELECT advisory_id FROM advisories_dirty") == [("CVE-2026-1111",)]
    monkeypatch.setattr(changes_mod, "apply", real)
    pipeline.run_osv_incremental()  # レコードは取り込み済み (ハッシュ同一) でも dirty から回収される
    assert [e["advisory_id"] for e in events(pipeline)] == ["CVE-2026-1111"]
    assert q(pipeline, "SELECT COUNT(*) FROM advisories_dirty") == [(0,)]


def test_bootstrap_resume_keeps_first_head(env):
    pipeline, osv, _, _ = env
    osv.fail_on = "Debian"
    with pytest.raises(RuntimeError):
        pipeline.bootstrap()
    first_head = osv.head
    osv.head = "2026-10-22T00:00:00Z"  # 再開までに時間が経った
    osv.fail_on = None
    pipeline.bootstrap()
    assert pipeline.osv_cursor() == first_head


def test_incremental_reads_overlap_but_skips_known_records(env):
    pipeline, osv, _, _ = env
    pipeline.bootstrap()
    seen: list[str] = []
    osv.modified_since = lambda cursor: seen.append(cursor) or [  # type: ignore[method-assign]
        ModifiedEntry("2026-10-01T00:00:00Z", "PyPI", "GHSA-aaaa-bbbb-cccc"),  # 取り込み済みと同じ modified
    ]
    fetched: list[str] = []
    osv.fetch_record = lambda eco, rid: fetched.append(rid)  # type: ignore[method-assign]
    pipeline.run_osv_incremental()
    assert seen == ["2026-10-19T22:00:00.000000Z"]  # カーソル (head) の 2 時間前から
    assert fetched == []


def test_malformed_record_is_skipped_not_fatal(env):
    pipeline, osv, _, _ = env
    osv.zips = {"PyPI": [{"id": "BAD-1", "affected": ["not-a-dict"]}, ghsa()]}
    pipeline.bootstrap()
    assert q(pipeline, "SELECT record_id FROM osv_records") == [("GHSA-aaaa-bbbb-cccc",)]
    assert q(pipeline, "SELECT skipped FROM source_runs WHERE source = 'osv_full'") == [(1,)]


def test_suspiciously_small_kev_snapshot_is_refused(env):
    pipeline, _, remote, _ = env
    pipeline.bootstrap()
    remote[KEV_URL] = json.dumps({"vulnerabilities": []}).encode()
    with pytest.raises(ValueError, match="too small"):
        pipeline.run_kev()
    assert q(pipeline, "SELECT COUNT(*) FROM kev_entries") == [(2,)]


# ── PR #227 レビュー指摘 (2 回目) の回帰テスト ────────────────────────────


def test_malformed_incremental_record_does_not_stall_cursor(env):
    pipeline, osv, _, _ = env
    pipeline.bootstrap()
    good = ghsa(fixed="2.4.4") | {"modified": "2026-10-21T00:00:00Z"}
    osv.records = {"BAD-1": MalformedRecord("PyPI/BAD-1: invalid JSON"), good["id"]: good}
    osv.modified = [ModifiedEntry("2026-10-21T00:00:01Z", "PyPI", "BAD-1"),
                    ModifiedEntry("2026-10-21T00:00:00Z", "PyPI", good["id"])]
    pipeline.run_osv_incremental()
    assert pipeline.osv_cursor() == "2026-10-21T00:00:01Z"
    assert [e["advisory_id"] for e in events(pipeline)] == ["CVE-2026-1111"]
    assert q(pipeline, "SELECT skipped FROM source_runs WHERE source = 'osv'") == [(1,)]


def test_missing_records_are_tracked_and_retried(env):
    pipeline, osv, _, _ = env
    pipeline.bootstrap()
    osv.modified = [ModifiedEntry("2026-10-21T00:00:00Z", "PyPI", "GHSA-gone-gone-gone")]
    pipeline.run_osv_incremental()
    assert q(pipeline, "SELECT record_id, attempts FROM osv_missing") == [("GHSA-gone-gone-gone", 1)]
    assert pipeline.missing_count() == 1
    # 次の実行では modified_id.csv の範囲外になっていても取り直す
    osv.modified = []
    pipeline.run_osv_incremental()
    assert q(pipeline, "SELECT attempts FROM osv_missing") == [(2,)]
    osv.records = {"GHSA-gone-gone-gone": {"id": "GHSA-gone-gone-gone", "modified": "2026-10-21T00:00:00Z",
                                           "aliases": ["CVE-2026-5555"]}}
    pipeline.run_osv_incremental()
    assert pipeline.missing_count() == 0
    assert q(pipeline, "SELECT 1 FROM advisories WHERE advisory_id = 'CVE-2026-5555'") == [(1,)]


def test_incremental_respects_ecosystem_filter(env):
    pipeline, osv, _, _ = env
    pipeline.ecosystems = ["PyPI"]
    pipeline.bootstrap()
    assert sorted(osv.downloaded) == ["PyPI"]
    osv.modified = [ModifiedEntry(f"2026-10-21T00:00:0{i}Z", "Debian", f"DSA-{i}") for i in reversed(range(5))]
    osv.downloaded.clear()
    fetched: list[str] = []
    osv.fetch_record = lambda eco, rid: fetched.append(rid)  # type: ignore[method-assign]
    pipeline.run_osv_incremental()
    assert osv.downloaded == [] and fetched == []
    assert pipeline.osv_cursor() == "2026-10-21T00:00:04Z"  # 対象外でもカーソルは進む


def test_two_level_alias_chain_is_rekeyed(env):
    pipeline, osv, _, _ = env
    osv.zips = {"PyPI": [
        {"id": "G2", "modified": "2026-10-01T00:00:00Z"},
        {"id": "G1", "modified": "2026-10-01T00:00:00Z", "aliases": ["G2"]},
        {"id": "P1", "modified": "2026-10-01T00:00:00Z", "aliases": ["G1"]},
    ]}
    pipeline.bootstrap()
    assert set(q(pipeline, "SELECT advisory_id FROM osv_records")) == {("G2",)}
    g2 = {"id": "G2", "modified": "2026-10-21T00:00:00Z", "aliases": ["CVE-2026-6666"]}
    osv.records = {"G2": g2}
    osv.modified = [ModifiedEntry("2026-10-21T00:00:00Z", "PyPI", "G2")]
    pipeline.run_osv_incremental()
    assert set(q(pipeline, "SELECT record_id, advisory_id FROM osv_records")) == {
        ("G2", "CVE-2026-6666"), ("G1", "CVE-2026-6666"), ("P1", "CVE-2026-6666"),
    }


def test_epss_rejects_truncated_snapshot(env):
    pipeline, _, remote, _ = env
    pipeline.bootstrap()
    remote[EPSS_URL] = epss_body({}, day="2026-10-24")
    with pytest.raises(ValueError, match="too small"):
        pipeline.run_epss()
    assert q(pipeline, "SELECT COUNT(*) FROM epss_scores") == [(2,)]


def test_epss_model_change_suppresses_rise_events(env):
    pipeline, _, remote, _ = env
    pipeline.bootstrap()
    remote[EPSS_URL] = epss_body({"CVE-2026-1111": 0.9, "CVE-2026-2001": 0.9}, day="2026-10-24", model="v2027")
    pipeline.run_epss()
    assert events(pipeline) == []
    assert q(pipeline, "SELECT epss FROM epss_scores WHERE cve = 'CVE-2026-1111'") == [(0.9,)]


def test_same_epss_day_is_not_reingested(env):
    pipeline, *_ , paths = env
    pipeline.bootstrap()
    pipeline.run_epss()
    assert len(list((paths.raw_dir / "epss").rglob("*.csv.gz"))) == 1


def test_unchanged_kev_is_not_saved_again(env):
    pipeline, *_ , paths = env
    pipeline.bootstrap()
    pipeline.run_kev()
    files = list((paths.raw_dir / "kev").rglob("*.json"))
    assert len(files) == 1
    ref = q(pipeline, "SELECT DISTINCT raw_ref FROM kev_entries")
    assert ref == [(str(files[0].relative_to(paths.root)),)]


def test_failed_full_refresh_removes_partial_download(env):
    pipeline, osv, _, paths = env
    pipeline.bootstrap()
    osv.fail_on = "npm"  # PyPI まで落としてから失敗
    with pytest.raises(RuntimeError):
        pipeline.run_osv_full()
    (failed_run,) = q(pipeline, "SELECT run_id FROM source_runs WHERE source = 'osv_full' AND status = 'failed'")
    assert not list(paths.raw_dir.glob(f"osv/dt=*/full-{failed_run[0]}"))
    osv.fail_on = None
    pipeline.run_osv_full()
    pipeline.run_osv_full()
    assert len({p.name for p in paths.raw_dir.glob("osv/dt=*/full-*")}) == 2  # 完了した 2 世代だけ


def test_full_download_stops_when_disk_is_low(env, monkeypatch):
    from src.common import raw_store
    from src.common.raw_store import DiskFull

    pipeline, osv, _, _ = env
    pipeline.raw._min_free = 10**9
    monkeypatch.setattr(raw_store.shutil, "disk_usage", lambda _p: type("U", (), {"free": 10})())
    with pytest.raises(DiskFull):
        pipeline.bootstrap()
    assert osv.downloaded == []
