"""本番イメージの SBOM (CycloneDX) の読み込みのテスト。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.detection.image_sbom import InvalidSbom, parse_image_sbom, parse_purl

DIGEST = "sha256:" + "a" * 64


def cdx(path: Path, *components: dict[str, Any]) -> Path:
    path.write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "components": list(components)}))
    return path


def deb(name: str, version: str, **q: str) -> dict[str, Any]:
    qs = "&".join(f"{k}={v}" for k, v in {"arch": "amd64", "distro": "debian-12.15", **q}.items())
    return {"type": "library", "name": name, "version": version,
            "purl": f"pkg:deb/debian/{name}@{version.replace('+', '%2B').replace(':', '%3A')}?{qs}"}


def test_parse_purl_decodes_parts():
    assert parse_purl("pkg:deb/debian/bsdutils@1%3A2.38.1-5%2Bdeb12u3?arch=amd64&upstream=util-linux%402.38.1") == (
        "deb", "debian", "bsdutils", "1:2.38.1-5+deb12u3", {"arch": "amd64", "upstream": "util-linux@2.38.1"},
    )
    assert parse_purl("pkg:npm/%40scope/name@1.0.0")[1:4] == ("@scope", "name", "1.0.0")
    with pytest.raises(ValueError):
        parse_purl("not-a-purl")


def test_debian_packages_use_source_package(tmp_path):
    path = cdx(
        tmp_path / "s.json",
        deb("libssl3", "3.0.22-1~deb12u1", upstream="openssl"),
        deb("openssl", "3.0.22-1~deb12u1"),  # ソース名と同じ → 1 つにまとまる
        deb("bsdutils", "1:2.38.1-5+deb12u3", upstream="util-linux%402.38.1-5%2Bdeb12u3"),
        {"type": "operating-system", "name": "debian", "version": "12.15"},
        {"type": "file", "name": "/etc/passwd"},
    )
    parsed = parse_image_sbom(path, "image:x", DIGEST)
    assert (parsed.kind, parsed.subject, parsed.sha256) == ("image", DIGEST, "a" * 64)
    assert [(c.ecosystem, c.name, c.version, c.purl) for c in parsed.components] == [
        ("Debian:12", "openssl", "3.0.22-1~deb12u1", "pkg:deb/debian/openssl@3.0.22-1~deb12u1?distro=debian-12"),
        # バイナリ (bsdutils) の epoch ではなく、ソースパッケージのバージョンを使う
        ("Debian:12", "util-linux", "2.38.1-5+deb12u3",
         "pkg:deb/debian/util-linux@2.38.1-5%2Bdeb12u3?distro=debian-12"),
    ]
    assert all(c.scope == "runtime" and not c.is_direct for c in parsed.components)


def test_distro_falls_back_to_operating_system(tmp_path):
    no_distro = {"type": "library", "name": "zlib1g", "version": "1:1.2.13.dfsg-1",
                 "purl": "pkg:deb/debian/zlib1g@1%3A1.2.13.dfsg-1?upstream=zlib"}
    path = cdx(tmp_path / "s.json", no_distro, {"type": "operating-system", "name": "debian", "version": "13.1"})
    assert [(c.ecosystem, c.name) for c in parse_image_sbom(path, "x", DIGEST).components] == [("Debian:13", "zlib")]


def test_runtimes_and_libraries(tmp_path):
    path = cdx(
        tmp_path / "s.json",
        {"type": "application", "name": "python", "version": "3.12.16", "purl": "pkg:generic/python@3.12.16"},
        deb("nodejs", "24.22.1-1nodesource1"),  # NodeSource の apt: Debian ではなく実行環境として照合
        {"type": "library", "name": "pip", "version": "25.0.1", "purl": "pkg:pypi/pip@25.0.1"},
        {"type": "library", "name": "Brotli", "version": "1.1.0", "purl": "pkg:pypi/Brotli@1.1.0"},
        {"type": "library", "name": "@scope/x", "version": "2.0.0", "purl": "pkg:npm/%40scope/x@2.0.0"},
        {"type": "library", "name": "busybox", "version": "1.36", "purl": "pkg:apk/alpine/busybox@1.36?distro=3.20"},
        {"type": "application", "name": "Simple Launcher", "version": "1.1"},  # purl なし
    )
    got = {(c.ecosystem, c.name, c.version) for c in parse_image_sbom(path, "x", DIGEST).components}
    assert got == {
        ("Bitnami", "python", "3.12.16"), ("Bitnami", "node", "24.22.1"),
        ("PyPI", "pip", "25.0.1"), ("PyPI", "brotli", "1.1.0"), ("npm", "@scope/x", "2.0.0"),
        ("purl:apk", "alpine/busybox", "1.36"),  # 未対応のエコシステムとして残す
    }


def test_invalid_sbom(tmp_path):
    (tmp_path / "bad.json").write_text("{")
    (tmp_path / "spdx.json").write_text(json.dumps({"spdxVersion": "SPDX-2.3"}))
    for name in ("bad.json", "spdx.json", "missing.json"):
        with pytest.raises(InvalidSbom):
            parse_image_sbom(tmp_path / name, "x", DIGEST)
