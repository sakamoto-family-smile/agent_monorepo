"""OSV レコード変換と名寄せ規則のテスト。"""
from __future__ import annotations

from src.intel.grouping import resolve_advisory_id
from src.intel.osv_record import parse_record

GHSA = {
    "id": "GHSA-aaaa-bbbb-cccc",
    "modified": "2026-10-01T00:00:00Z",
    "published": "2026-09-01T00:00:00Z",
    "aliases": ["CVE-2026-1111", "PYSEC-2026-1"],
    "summary": "  Remote   code execution in examplelib ",
    "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
    "database_specific": {"severity": "CRITICAL"},
    "affected": [
        {
            "package": {"ecosystem": "PyPI", "name": "examplelib", "purl": "pkg:pypi/examplelib"},
            "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.4.3"}]}],
            "versions": ["2.4.0", "2.4.1"],
        }
    ],
}


def test_parse_record_extracts_fields():
    rec = parse_record(GHSA)
    assert rec.record_id == "GHSA-aaaa-bbbb-cccc"
    assert rec.db_prefix == "GHSA"
    assert rec.cves == {"CVE-2026-1111"}
    assert rec.summary == "Remote code execution in examplelib"
    assert rec.cvss_score == 9.8
    assert rec.severity_label == "CRITICAL"
    assert rec.affected[0].fixed == ["2.4.3"]
    assert rec.affected[0].versions_count == 2


def test_content_hash_is_stable_and_sensitive():
    assert parse_record(GHSA).content_hash == parse_record(dict(GHSA)).content_hash
    changed = {**GHSA, "modified": "2026-10-02T00:00:00Z"}
    assert parse_record(changed).content_hash != parse_record(GHSA).content_hash


def test_bad_cvss_vector_is_ignored():
    rec = parse_record({"id": "X-1", "severity": [{"type": "CVSS_V3", "score": "garbage"}]})
    assert rec.cvss_score is None and rec.cvss_vector is None


def test_single_cve_groups_by_cve():
    assert resolve_advisory_id(parse_record(GHSA), lambda _a: None) == "CVE-2026-1111"


def test_upstream_cve_counts_for_distro_records():
    rec = parse_record({"id": "DEBIAN-CVE-2026-2222", "upstream": ["CVE-2026-2222"]})
    assert resolve_advisory_id(rec, lambda _a: None) == "CVE-2026-2222"


def test_bundle_with_many_cves_stays_independent():
    rec = parse_record({"id": "USN-7000-1", "upstream": ["CVE-2026-1", "CVE-2026-2"]})
    assert resolve_advisory_id(rec, lambda _a: "CVE-2026-1") == "USN-7000-1"


def test_cveless_record_joins_alias_target():
    rec = parse_record({"id": "PYSEC-2026-9", "aliases": ["GHSA-zzzz-zzzz-zzzz"]})
    assert resolve_advisory_id(rec, {"GHSA-zzzz-zzzz-zzzz": "GHSA-zzzz-zzzz-zzzz"}.get) == "GHSA-zzzz-zzzz-zzzz"
    assert resolve_advisory_id(rec, lambda _a: None) == "PYSEC-2026-9"


def test_severity_label_falls_back_to_summary_prefix():
    """AlmaLinux 等は深刻度を summary 先頭 ("Important: ...") にだけ書く。"""
    alsa = {"id": "ALSA-2026:A014", "summary": "Important: php:8.1 security update", "affected": []}
    assert parse_record(alsa).severity_label == "HIGH"
    assert parse_record({**alsa, "summary": "Moderate: x"}).severity_label == "MEDIUM"
    assert parse_record({**alsa, "summary": "Importantly broken"}).severity_label is None
    # 構造化フィールドがあればそちらを優先
    assert parse_record({**alsa, "database_specific": {"severity": "LOW"}}).severity_label == "LOW"


def test_versions_kept_only_without_evaluable_range():
    """ECOSYSTEM / SEMVER の範囲があれば範囲で判定できるので、列挙された versions は持たない。"""
    mal = {
        "id": "MAL-2026-1", "modified": "2026-10-01T00:00:00Z",
        "affected": [
            {"package": {"ecosystem": "npm", "name": "evil"}, "versions": ["1.0.1", "1.0.0"]},
            {"package": {"ecosystem": "PyPI", "name": "gitonly"},
             "ranges": [{"type": "GIT", "repo": "https://x", "events": [{"introduced": "abc"}]}],
             "versions": ["0.1"]},
        ],
    }
    assert [a.versions for a in parse_record(mal).affected] == [("1.0.0", "1.0.1"), ("0.1",)]
    assert parse_record(GHSA).affected[0].versions == ()
    assert parse_record(GHSA).affected[0].versions_count == 2
