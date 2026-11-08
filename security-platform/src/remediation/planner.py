"""改修の対象を選ぶ (detection.db を読み取り専用で見る)。

対象にするのは、次をすべて満たす Finding:

- サービスが ``auto_remediation: true`` で、lockfile に ``uv.lock`` がある (npm は後の段階)
- ``open`` で修正版がある (``fix_type = 'upgrade'``)、優先度が ``min_priority`` まで
- 見つかった元がそのサービスの ``uv.lock`` (本番イメージだけにあるものは lockfile を直しても消えない)

パッケージごとに、全 Advisory を直せる版 (各 Finding の修正版のうち最大) まで上げる。
Finding の修正版は「今の版より上で最初に出た修正」なので、範囲が複数ある Advisory ではその版でもまだ
当たることがある。refine で上げる先の版を intel で照合し直し、当たらなくなる版まで引き上げる。
メジャーバージョンが上がるもの (0.x は 2 つ目の数字) と、前に同じ版で失敗したものは今回は見送る
(破壊的な変更を含みうるので、LLM による修正案 (後の段階) か人に回す)。
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, replace

from packaging.version import InvalidVersion, Version
from sqlalchemy import Engine, text

from ..common.services import Service
from ..detection.lockfiles import Component, canonical_pypi_name
from ..detection.matcher import Matcher
from ..detection.triage import PRIORITIES

LOCKFILE = "uv.lock"
ECOSYSTEM = "PyPI"
MAX_REFINE = 5


@dataclass(frozen=True)
class Bump:
    name: str  # PEP 503 で正規化した名前
    current: str
    target: str
    priority: str  # このパッケージの Finding のうち最も高い優先度
    finding_ids: tuple[str, ...]


@dataclass(frozen=True)
class Skip:
    name: str
    current: str
    target: str | None
    reason: str  # major / attempted / multiple_versions / invalid_version / unresolved


@dataclass(frozen=True)
class Plan:
    service: Service
    lockfile: str  # モノレポのルートからのパス (例: ``svc/uv.lock``)
    bumps: tuple[Bump, ...]
    skipped: tuple[Skip, ...]

    @property
    def manual(self) -> bool:
        """P1 (悪性・KEV) を含むなら自動マージせず、人がマージする。"""
        return any(b.priority == "P1" for b in self.bumps)

    def finding_ids(self) -> tuple[str, ...]:
        return tuple(f for b in self.bumps for f in b.finding_ids)


def _major(v: Version) -> tuple[int, ...]:
    """互換性が崩れうる桁。1.x 以上は 1 つ目、0.x は 2 つ目まで (semver の慣習)。"""
    release = (*v.release, 0)
    return (0, release[1]) if release[0] == 0 else (release[0],)


def is_major_bump(current: str, target: str) -> bool:
    return _major(Version(target)) > _major(Version(current))


def plan_service(
    detection: Engine, service: Service, min_priority: str, attempted: set[tuple[str, str]],
) -> Plan | None:
    """サービス 1 つ分。対象が無ければ None。attempted は前に失敗した (名前, 版)。"""
    if LOCKFILE not in service.lockfiles:
        return None
    lockfile = f"{service.path}{LOCKFILE}"
    allowed = PRIORITIES[: PRIORITIES.index(min_priority) + 1]
    with detection.connect() as conn:
        rows = conn.execute(text(
            "SELECT finding_id, priority, fixed_version, evidence_json FROM findings "
            "WHERE state = 'open' AND service_id = :s AND fix_type = 'upgrade' ORDER BY finding_id"
        ), {"s": service.id}).all()
    groups: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    for finding_id, priority, fixed, ev_json in rows:
        ev = json.loads(ev_json)
        if (ev.get("source_kind"), ev.get("source"), ev.get("ecosystem")) != ("source", lockfile, ECOSYSTEM):
            continue
        if priority not in allowed or not fixed:
            continue
        groups[canonical_pypi_name(str(ev["package"]))].append((finding_id, priority, fixed, str(ev["version"])))
    bumps: list[Bump] = []
    skipped: list[Skip] = []
    for name in sorted(groups):
        items = groups[name]
        currents = {i[3] for i in items}
        if len(currents) > 1:  # 環境ごとに別の版に解決されている。1 つの指定では上げきれない
            skipped.append(Skip(name, ",".join(sorted(currents)), None, "multiple_versions"))
            continue
        current = currents.pop()
        try:
            target = max((i[2] for i in items), key=Version)
            major = is_major_bump(current, target)
        except InvalidVersion:
            skipped.append(Skip(name, current, None, "invalid_version"))
            continue
        if major:
            skipped.append(Skip(name, current, target, "major"))
        elif (name, target) in attempted:
            skipped.append(Skip(name, current, target, "attempted"))
        else:
            priority = min((i[1] for i in items), key=PRIORITIES.index)
            bumps.append(Bump(name, current, target, priority, tuple(i[0] for i in items)))
    if not bumps and not skipped:
        return None
    # 優先度の高い順 (1 つずつに分けるときはこの順に出す)
    bumps.sort(key=lambda b: (PRIORITIES.index(b.priority), b.name))
    return Plan(service, lockfile, tuple(bumps), tuple(skipped))


def refine(plan: Plan, intel: Engine | None) -> Plan:
    """上げる先の版を intel で照合し、修正版のある Advisory がまだ当たるなら、その修正版まで引き上げる。"""
    if intel is None or not plan.bumps:
        return plan
    matcher = Matcher(intel)
    bumps: list[Bump] = []
    skipped = list(plan.skipped)
    for b in plan.bumps:
        target: str | None = b.target
        for _ in range(MAX_REFINE):
            comp = Component(ECOSYSTEM, b.name, target, f"pkg:pypi/{b.name}@{target}", True, "runtime")
            fixes = [m.fixed_version for m in matcher.match([comp])[0] if m.fixed_version]
            if not fixes:
                break
            target = max(fixes, key=Version)
        else:
            target = None
        if target is None:
            skipped.append(Skip(b.name, b.current, b.target, "unresolved"))
        elif is_major_bump(b.current, target):
            skipped.append(Skip(b.name, b.current, target, "major"))
        else:
            bumps.append(replace(b, target=target))
    return replace(plan, bumps=tuple(bumps), skipped=tuple(skipped))
