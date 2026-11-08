"""差分検査: updater が返した uv.lock を PR にしてよいかを決める。

updater はパッケージのコードを動かしうる隔離環境なので、返ってきた uv.lock は信頼しない。
次をすべて満たすときだけ通す (どれか 1 つでも外れたら PR にしない):

1. lockfile の設定 (version・revision・requires-python・resolution-markers など package 以外) が変わっていない
2. 名前と版が同じパッケージは、中身 (取得元・ハッシュ・依存) も前と完全に同じ
3. 上げたパッケージは指定した版になっている
4. それ以外に変わったパッケージ (追加・削除・版の変化) は MAX_OTHER_CHANGES 個まで、メジャーバージョンは上がらない
5. 新しい版の取得元は前と同じ PyPI のインデックス、ファイルの URL は files.pythonhosted.org、sha256 のハッシュ付き
6. 新しい版を intel の Advisory で照合して、新しく当たるもの・修正版があるのに残るものが無い
   (悪性パッケージへの差し替えや、上げた先にも残る脆弱性を止める)
"""
from __future__ import annotations

import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from packaging.version import InvalidVersion, Version
from sqlalchemy import Engine

from ..detection.lockfiles import Component, canonical_pypi_name, parse_uv_lock
from ..detection.matcher import Matcher
from .planner import is_major_bump

MAX_OTHER_CHANGES = 5
REGISTRY = "https://pypi.org/simple"
FILE_HOSTS = frozenset({"files.pythonhosted.org"})


@dataclass(frozen=True)
class Change:
    name: str
    old: tuple[str, ...]  # 前の版 (無ければ追加)
    new: tuple[str, ...]  # 後の版 (無ければ削除)


@dataclass
class GuardResult:
    problems: list[str] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    residual: list[str] = field(default_factory=list)  # 修正版の無い Advisory が残るもの (止めはしない)

    @property
    def ok(self) -> bool:
        return not self.problems


def _packages(data: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """名前 → 版 → エントリ。"""
    out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for p in data.get("package") or []:
        if isinstance(p, dict) and "name" in p:
            out[canonical_pypi_name(str(p["name"]))][str(p.get("version", ""))] = p
    return out


def _check_entry(name: str, version: str, entry: dict[str, Any], registry: str) -> list[str]:
    problems = []
    if entry.get("source") != {"registry": registry}:
        problems.append(f"{name} {version}: 取得元が {registry} ではない ({entry.get('source')})")
    files = [entry["sdist"]] if isinstance(entry.get("sdist"), dict) else []
    files += [w for w in entry.get("wheels") or [] if isinstance(w, dict)]
    if not files:
        problems.append(f"{name} {version}: 配布ファイルが無い")
    for f in files:
        host = urlparse(str(f.get("url", ""))).hostname
        if host not in FILE_HOSTS:
            problems.append(f"{name} {version}: 配布ファイルの取得先が {host}")
        if not str(f.get("hash", "")).startswith("sha256:"):
            problems.append(f"{name} {version}: ハッシュが無い")
    return problems


def _same_version(a: str, b: str) -> bool:
    try:
        return Version(a) == Version(b)
    except InvalidVersion:
        return a == b


def check(
    old_text: str, new_text: str, requested: dict[str, str], *, intel: Engine | None = None,
    max_other: int = MAX_OTHER_CHANGES,
) -> GuardResult:
    """requested は (正規化した名前 → 上げる版)。intel が無ければ 6 は飛ばす (テスト用)。"""
    r = GuardResult()
    try:
        old, new = tomllib.loads(old_text), tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as e:
        r.problems.append(f"uv.lock を読めない: {e}")
        return r
    # revision (lockfile の形式の版) は uv が新しいと上がる。上がるだけなら許す (中身は 2 で同じことを確かめる)
    old_meta = {k: v for k, v in old.items() if k not in ("package", "revision")}
    new_meta = {k: v for k, v in new.items() if k not in ("package", "revision")}
    if old_meta != new_meta:
        keys = sorted(k for k in old_meta.keys() | new_meta.keys() if old_meta.get(k) != new_meta.get(k))
        r.problems.append(f"lockfile の設定が変わった: {', '.join(keys)}")
    if not isinstance(new.get("revision", 0), int) or new.get("revision", 0) < old.get("revision", 0):
        r.problems.append(f"lockfile の revision が下がった ({old.get('revision')} → {new.get('revision')})")
    registry = next((p["source"]["registry"] for p in old.get("package") or []
                     if isinstance(p.get("source"), dict) and "registry" in p["source"]), REGISTRY)
    old_pkgs, new_pkgs = _packages(old), _packages(new)

    for name in sorted(old_pkgs.keys() | new_pkgs.keys()):
        before, after = old_pkgs.get(name, {}), new_pkgs.get(name, {})
        for version in sorted(before.keys() & after.keys()):
            if before[version] != after[version]:
                r.problems.append(f"{name} {version}: 版が同じなのに中身が変わった")
        if set(before) == set(after):
            continue
        r.changes.append(Change(name, tuple(sorted(before)), tuple(sorted(after))))
        for version in sorted(set(after) - set(before)):
            r.problems += _check_entry(name, version, after[version], registry)

    for name, target in sorted(requested.items()):
        got = tuple(sorted(new_pkgs.get(name, {})))
        if len(got) != 1 or not _same_version(got[0], target):  # 2.9 と 2.9.0 は同じ版 (PEP 440)
            r.problems.append(f"{name}: {target} に上がっていない ({', '.join(got) or 'なし'})")
    others = [c for c in r.changes if c.name not in requested]
    if len(others) > max_other:
        r.problems.append(f"指定以外のパッケージが {len(others)} 個変わった (上限 {max_other})")
    for c in others:
        if len(c.old) == 1 and len(c.new) == 1:
            try:
                if is_major_bump(c.old[0], c.new[0]):
                    r.problems.append(f"{c.name}: メジャーバージョンが上がった ({c.old[0]} → {c.new[0]})")
            except InvalidVersion:
                r.problems.append(f"{c.name}: 版を解釈できない ({c.old[0]} → {c.new[0]})")
    if intel is not None and r.changes:
        _recheck(old_text, new_text, {c.name for c in r.changes}, intel, r)
    return r


def _recheck(old_text: str, new_text: str, names: set[str], intel: Engine, r: GuardResult) -> None:
    """変わったパッケージの新旧を照合し、新しく当たる Advisory と、修正版があるのに残るものを止める。"""
    def components(text: str) -> list[Component]:
        return [c for c in parse_uv_lock(text) if canonical_pypi_name(c.name) in names]

    matcher = Matcher(intel)
    before = {(canonical_pypi_name(m.component.name), m.advisory.advisory_id)
              for m in matcher.match(components(old_text))[0]}
    for m in matcher.match(components(new_text))[0]:
        name, adv = canonical_pypi_name(m.component.name), m.advisory.advisory_id
        label = f"{name} {m.component.version}: {adv}"
        if m.advisory.kind in ("malicious", "compromised"):
            r.problems.append(f"{label} (悪性・侵害) に当たる")
        elif (name, adv) not in before:
            r.problems.append(f"{label} に新しく当たる")
        elif m.fixed_version:
            r.problems.append(f"{label} が残る ({m.fixed_version} で直る)")
        else:
            r.residual.append(f"{label} (修正版なし)")
