"""OSV の影響範囲 (ranges / versions) とパッケージのバージョンの比較。

対応するエコシステム:
- PyPI (PEP 440)・npm (SemVer): lockfile とイメージ内のライブラリ
- Debian:<版> (dpkg の比較規則): イメージの OS パッケージ
- Bitnami (SemVer): イメージの実行環境 (Python・Node.js 本体)。Bitnami の Advisory は
  上流のバージョン番号で範囲を持つので、公式イメージの /usr/local の本体と比べられる
- VSCode / VSCode:<マーケットプレイス> (SemVer): 開発 PC のエディタ拡張 (host_inventory.py)。
  VS Code は ``VSCode``、Open VSX から入れるエディタ (Cursor など) は ``VSCode:https://open-vsx.org``
比べられないもの (未対応のエコシステム・解釈できないバージョン) は ``None`` を返し、呼び出し側で数える。
範囲の評価は OSV スキーマの手順に従う: イベントをバージョン順に並べ、
introduced で影響あり、fixed で影響なし、last_affected を超えたら影響なしにする。
"""
from __future__ import annotations

import re
from functools import total_ordering
from typing import Any

from packaging.version import InvalidVersion, Version

SEMVER_ECOSYSTEMS = frozenset({"npm", "Bitnami"})
DEBIAN_PREFIX = "Debian:"
VSCODE = "VSCode"
OPEN_VSX = "VSCode:https://open-vsx.org"
EVALUABLE_RANGE_TYPES = frozenset({"ECOSYSTEM", "SEMVER"})

_SEMVER = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-.]+)?$"
)


@total_ordering
class _Min:
    """introduced: "0" (最初のバージョンから影響あり) を表す最小値。"""

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Min)

    def __lt__(self, other: object) -> bool:
        return not isinstance(other, _Min)

    def __hash__(self) -> int:
        return 0


MIN = _Min()


def is_vscode(ecosystem: str) -> bool:
    return ecosystem == VSCODE or ecosystem.startswith(f"{VSCODE}:")


def _is_semver(ecosystem: str) -> bool:
    return ecosystem in SEMVER_ECOSYSTEMS or is_vscode(ecosystem)


def is_supported(ecosystem: str) -> bool:
    return ecosystem == "PyPI" or _is_semver(ecosystem) or ecosystem.startswith(DEBIAN_PREFIX)


def _dpkg_order(c: str) -> int:
    # dpkg の verrevcmp: "~" は終端より前、英字は記号より前
    if c == "~":
        return -1
    if c.isalpha():
        return ord(c)
    return ord(c) + 256


def _dpkg_part_cmp(a: str, b: str) -> int:
    """upstream_version / debian_revision どうしの比較 (dpkg の verrevcmp)。"""
    i = j = 0
    while i < len(a) or j < len(b):
        while (i < len(a) and not a[i].isdigit()) or (j < len(b) and not b[j].isdigit()):
            ac = _dpkg_order(a[i]) if i < len(a) and not a[i].isdigit() else 0
            bc = _dpkg_order(b[j]) if j < len(b) and not b[j].isdigit() else 0
            if ac != bc:
                return -1 if ac < bc else 1
            i += 1
            j += 1
        while i < len(a) and a[i] == "0":
            i += 1
        while j < len(b) and b[j] == "0":
            j += 1
        first_diff = 0
        while i < len(a) and a[i].isdigit() and j < len(b) and b[j].isdigit():
            if not first_diff:
                first_diff = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < len(a) and a[i].isdigit():
            return 1
        if j < len(b) and b[j].isdigit():
            return -1
        if first_diff:
            return -1 if first_diff < 0 else 1
    return 0


_DPKG = re.compile(r"^(?:(\d+):)?([0-9][A-Za-z0-9.+~:-]*?)(?:-([A-Za-z0-9.+~]+))?$")


@total_ordering
class DebianVersion:
    """Debian のバージョン ([epoch:]upstream_version[-debian_revision])。"""

    def __init__(self, value: str) -> None:
        m = _DPKG.match(value)
        if m is None:
            raise ValueError(value)
        self.epoch = int(m.group(1) or 0)
        self.upstream = m.group(2)
        self.revision = m.group(3) or ""

    def _cmp(self, other: DebianVersion) -> int:
        if self.epoch != other.epoch:
            return -1 if self.epoch < other.epoch else 1
        return _dpkg_part_cmp(self.upstream, other.upstream) or _dpkg_part_cmp(self.revision, other.revision)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DebianVersion):
            return NotImplemented
        return self._cmp(other) == 0

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, DebianVersion):
            return NotImplemented
        return self._cmp(other) < 0

    def __hash__(self) -> int:
        return hash((self.epoch, self.upstream, self.revision))


def _semver_key(value: str) -> tuple[Any, ...]:
    m = _SEMVER.match(value)
    if m is None:
        raise ValueError(value)
    major, minor, patch, pre = m.groups()
    # プレリリースは正式版より前。識別子は数字 < 英数字、数字どうしは数値で比べる
    pre_key: tuple[Any, ...] = (1,) if pre is None else (0, *(
        (0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split(".")
    ))
    return (int(major), int(minor), int(patch), pre_key)


def version_key(ecosystem: str, value: str) -> Any:
    """比較用のキー。解釈できなければ ValueError。"""
    if value == "0":
        return MIN
    if ecosystem == "PyPI":
        try:
            return Version(value)
        except InvalidVersion as e:
            raise ValueError(value) from e
    if _is_semver(ecosystem):
        return _semver_key(value)
    if ecosystem.startswith(DEBIAN_PREFIX):
        return DebianVersion(value)
    raise ValueError(f"unsupported ecosystem: {ecosystem}")


def _event_value(event: dict[str, Any]) -> tuple[str, str] | None:
    for kind in ("introduced", "fixed", "last_affected"):
        if isinstance(event.get(kind), str):
            return kind, event[kind]
    return None  # limit 等は使わない


def in_range(ecosystem: str, version: str, rng: dict[str, Any]) -> bool | None:
    """1 つの range に入るか。評価できない range なら None。"""
    if rng.get("type") not in EVALUABLE_RANGE_TYPES:
        return None
    try:
        v = version_key(ecosystem, version)
        events = []
        for ev in rng.get("events") or []:
            kv = _event_value(ev) if isinstance(ev, dict) else None
            if kv is not None:
                events.append((version_key(ecosystem, kv[1]), kv[0]))
    except ValueError:
        return None
    affected = False
    for key, kind in sorted(events, key=lambda e: e[0]):
        if kind == "introduced" and v >= key:
            affected = True
        elif kind == "fixed" and v >= key or kind == "last_affected" and v > key:
            affected = False
    return affected


def is_affected(
    ecosystem: str, version: str, ranges: list[dict[str, Any]], versions: list[str]
) -> bool | None:
    """影響を受けるなら True、受けないなら False、どれも評価できなければ None。"""
    if versions:
        try:
            key = version_key(ecosystem, version)
            if any(version_key(ecosystem, x) == key for x in versions if x != "0"):
                return True
        except ValueError:
            if version in versions:
                return True
    results = [in_range(ecosystem, version, r) for r in ranges]
    if any(r is True for r in results):
        return True
    if versions or any(r is False for r in results):
        return False
    return None


def smallest_fix_above(ecosystem: str, version: str, fixed: list[str]) -> str | None:
    """今のバージョンより新しい修正版のうち最小のもの。"""
    try:
        current = version_key(ecosystem, version)
    except ValueError:
        return None
    candidates = []
    for f in fixed:
        try:
            key = version_key(ecosystem, f)
        except ValueError:
            continue
        if key > current:
            candidates.append((key, f))
    return min(candidates)[1] if candidates else None
