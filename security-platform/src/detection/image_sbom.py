"""本番イメージの SBOM (syft の CycloneDX JSON) から照合用のコンポーネント一覧を作る。

SBOM は ``make detection-images`` (images.py) がホストで作って data/sbom/images/ に置く。
ここはファイルを読むだけで、ネットワークには出ない。

- OS パッケージ (pkg:deb/debian): Debian の Advisory はソースパッケージ単位なので、
  purl の ``upstream`` (ソース名[@ソースのバージョン]) で引き当てる。エコシステムは ``Debian:<メジャー版>``
- 実行環境 (pkg:generic/python・node): 公式イメージが /usr/local に入れる本体。Bitnami の
  Advisory (上流のバージョン番号で範囲を持つ) で照合する。NodeSource の apt で入れた nodejs も同じ扱い
- ライブラリ (pkg:pypi・pkg:npm): lockfile と同じ表記にそろえる。lockfile に無いもの
  (ベースイメージの pip など) もここで拾える
それ以外 (Ubuntu・Alpine の OS パッケージ等) は ``purl:<type>`` のエコシステムで残し、未対応として数える。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from .lockfiles import Component, ParsedLockfile, _npm_purl, _pypi_purl, canonical_pypi_name

# syft が見つけた実行環境の本体 → Bitnami の Advisory でのパッケージ名
RUNTIMES = {"python": "python", "node": "node"}
# Debian 以外の apt リポジトリから入れた実行環境 ((パッケージ名, バージョンの目印) → Bitnami の名前)。
# Debian のセキュリティトラッカーとは版が違うので、上流のバージョンで実行環境として照合する
THIRD_PARTY_DEBS = {("nodejs", "nodesource"): "node"}
_DEBIAN_DISTRO = re.compile(r"^debian-(\d+)")


class InvalidSbom(ValueError):
    pass


def parse_purl(purl: str) -> tuple[str, str, str, str, dict[str, str]]:
    """purl を (type, namespace, name, version, qualifiers) に分ける (各部分は % を戻す)。"""
    if not purl.startswith("pkg:"):
        raise ValueError(purl)
    rest = purl[4:].split("#", 1)[0]
    rest, _, query = rest.partition("?")
    path, _, version = rest.rpartition("@") if "@" in rest else (rest, "", "")
    type_, _, path = path.partition("/")
    namespace, _, name = path.rpartition("/")
    qualifiers = {}
    for pair in query.split("&") if query else []:
        k, _, v = pair.partition("=")
        qualifiers[k.lower()] = unquote(v)
    return type_.lower(), unquote(namespace), unquote(name), unquote(version), qualifiers


def _debian(name: str, version: str, q: dict[str, str], os_major: str | None) -> Component | None:
    for (pkg, marker), runtime in THIRD_PARTY_DEBS.items():
        if name == pkg and marker in version:
            upstream = version.split(":", 1)[-1].split("-", 1)[0]
            return Component("Bitnami", runtime, upstream, f"pkg:generic/{runtime}@{upstream}", False, "runtime")
    m = _DEBIAN_DISTRO.match(q.get("distro", ""))
    major = m.group(1) if m else os_major
    if major is None:
        return None
    src, _, src_version = q.get("upstream", "").partition("@")
    src, version = (src or name), (src_version or version)
    purl = f"pkg:deb/debian/{quote(src, safe='')}@{quote(version, safe='')}?distro=debian-{major}"
    return Component(f"Debian:{major}", src, version, purl, False, "runtime")


def _component(purl: str, os_major: str | None) -> Component | None:
    try:
        type_, namespace, name, version, q = parse_purl(purl)
    except ValueError:
        return None
    if not name or not version:
        return None
    if type_ == "deb" and namespace == "debian":
        return _debian(name, version, q, os_major)
    if type_ == "pypi":
        return Component("PyPI", canonical_pypi_name(name), version, _pypi_purl(name, version), False, "runtime")
    if type_ == "npm":
        full = f"{namespace}/{name}" if namespace else name
        return Component("npm", full, version, _npm_purl(full, version), False, "runtime")
    if type_ == "generic" and name in RUNTIMES:
        return Component("Bitnami", RUNTIMES[name], version, f"pkg:generic/{name}@{version}", False, "runtime")
    return Component(f"purl:{type_}", f"{namespace}/{name}" if namespace else name, version,
                     purl.split("?", 1)[0], False, "runtime")


def _os_major(components: list[dict[str, Any]]) -> str | None:
    for c in components:
        if c.get("type") == "operating-system" and c.get("name") == "debian":
            m = re.match(r"^(\d+)", str(c.get("version") or ""))
            if m:
                return m.group(1)
    return None


def parse_image_sbom(path: Path, display_path: str, digest: str) -> ParsedLockfile:
    """``digest`` (sha256:...) はイメージのダイジェスト。SBOM の識別に使う。"""
    try:
        data = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as e:
        raise InvalidSbom(f"{path.name}: {e}") from e
    if not isinstance(data, dict) or data.get("bomFormat") != "CycloneDX":
        raise InvalidSbom(f"{path.name}: CycloneDX の JSON ではありません")
    raw = [c for c in data.get("components") or [] if isinstance(c, dict)]
    os_major = _os_major(raw)
    seen: dict[str, Component] = {}
    for c in raw:
        purl = c.get("purl")
        if isinstance(purl, str) and (comp := _component(purl, os_major)) is not None:
            seen.setdefault(comp.purl, comp)
    return ParsedLockfile(
        display_path, digest.removeprefix("sha256:"), tuple(sorted(seen.values(), key=lambda c: c.purl)),
        kind="image", subject=digest,
    )
