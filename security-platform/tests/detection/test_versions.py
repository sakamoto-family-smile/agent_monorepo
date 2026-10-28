"""影響範囲の評価のテスト。"""
from __future__ import annotations

import pytest

from src.detection.versions import in_range, is_affected, is_supported, smallest_fix_above, version_key


def eco(*events: dict[str, str], type_: str = "ECOSYSTEM") -> dict:
    return {"type": type_, "events": list(events)}


@pytest.mark.parametrize(("version", "expected"), [
    ("1.0.0", True), ("2.4.2", True), ("2.4.3", False), ("3.0", False), ("2.4.3rc1", True),
])
def test_pypi_introduced_fixed(version, expected):
    assert in_range("PyPI", version, eco({"introduced": "0"}, {"fixed": "2.4.3"})) is expected


def test_multiple_windows_and_last_affected():
    rng = eco({"introduced": "1.0"}, {"fixed": "1.2"}, {"introduced": "2.0"}, {"last_affected": "2.1"})
    assert [in_range("PyPI", v, rng) for v in ("0.9", "1.1", "1.2", "2.0.5", "2.1", "2.2")] == [
        False, True, False, True, True, False,
    ]


@pytest.mark.parametrize(("version", "expected"), [
    ("4.17.20", True), ("4.17.21", False), ("4.17.21-beta.1", True), ("5.0.0-0", False),
])
def test_npm_semver_with_prerelease(version, expected):
    rng = eco({"introduced": "0"}, {"fixed": "4.17.21"}, type_="SEMVER")
    assert in_range("npm", version, rng) is expected


def test_unevaluable_range_and_versions_list():
    git = {"type": "GIT", "repo": "x", "events": [{"introduced": "abc"}]}
    assert in_range("PyPI", "1.0", git) is None
    assert is_affected("PyPI", "1.0", [git], []) is None
    assert is_affected("npm", "1.0.1", [], ["1.0.0", "1.0.1"]) is True
    assert is_affected("npm", "1.0.2", [], ["1.0.0", "1.0.1"]) is False
    assert is_affected("PyPI", "1.0", [], ["1.0.0"]) is True  # PEP 440 では 1.0 == 1.0.0
    assert is_affected("PyPI", "not a version", [eco({"introduced": "0"})], []) is None


def test_smallest_fix_above():
    assert smallest_fix_above("PyPI", "2.4.0", ["2.3.9", "3.0", "2.4.3"]) == "2.4.3"
    assert smallest_fix_above("PyPI", "3.1", ["2.4.3", "3.0"]) is None


@pytest.mark.parametrize(("a", "b", "expected"), [
    ("1.0", "1.0", 0),
    ("1.0~rc1", "1.0", -1),           # ~ は正式版より前
    ("1.0", "1.0+b1", -1),
    ("1:1.0", "2.0", 1),              # epoch が最優先
    ("3.0.22-1~deb12u2", "3.0.22-1~deb12u1", 1),
    ("3.0.22-1~deb12u2", "3.0.22-1", -1),
    ("2.36-9+deb12u14", "2.36-9+deb12u13", 1),
    ("7.88.1-10+deb12u14", "7.88.1-10+deb12u5", 1),  # 数字の部分は数値で比べる
    ("1.0a", "1.0+", -1),             # 英字は記号より前
    ("1.0-1", "1.0", 1),
    ("1.002", "1.2", 0),
])
def test_debian_version_order(a, b, expected):
    ka, kb = version_key("Debian:12", a), version_key("Debian:12", b)
    assert ((ka > kb) - (ka < kb)) == expected


def test_debian_and_bitnami_ranges():
    deb = [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "3.0.22-1~deb12u2"}]}]
    assert is_affected("Debian:12", "3.0.22-1~deb12u1", deb, []) is True
    assert is_affected("Debian:12", "3.0.22-1~deb12u2", deb, []) is False
    assert is_affected("Debian:12", "1:0.1", deb, []) is False
    assert smallest_fix_above("Debian:12", "1.0-1", ["0.9", "1.0-2", "1:0.1"]) == "1.0-2"
    node = [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "22.23.2"},
                                          {"introduced": "23.0.0"}, {"fixed": "24.18.1"}]}]
    assert is_affected("Bitnami", "24.18.0", node, []) is True
    assert is_affected("Bitnami", "24.22.1", node, []) is False
    assert is_supported("Debian:13") and is_supported("Bitnami") and not is_supported("Ubuntu:24.04:LTS")
