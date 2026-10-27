"""OSV の影響範囲 (ranges / versions) とパッケージのバージョンの比較。

対応するのは lockfile から照合するエコシステム (PyPI・npm) だけ。比べられないもの
(未対応のエコシステム・解釈できないバージョン) は ``None`` を返し、呼び出し側で数える。
範囲の評価は OSV スキーマの手順に従う: イベントをバージョン順に並べ、
introduced で影響あり、fixed で影響なし、last_affected を超えたら影響なしにする。
"""
from __future__ import annotations

import re
from functools import total_ordering
from typing import Any

from packaging.version import InvalidVersion, Version

SUPPORTED_ECOSYSTEMS = frozenset({"PyPI", "npm"})
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
    if ecosystem == "npm":
        return _semver_key(value)
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
