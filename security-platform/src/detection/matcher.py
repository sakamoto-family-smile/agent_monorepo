"""コンポーネントと intel.db の Advisory の照合。

intel.db は読み取り契約のビュー (v_advisories / v_advisory_affected) だけを読む。
PyPI の名前は OSV 側の表記 (例: "Brotli") と lockfile 側 (正規化済み) で違うので、
OSV 側の名前一覧を正規化して引き当てる。取り下げ済みの Advisory は照合しない。
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import Engine, bindparam, text

from .lockfiles import Component, canonical_pypi_name
from .versions import SUPPORTED_ECOSYSTEMS, is_affected, smallest_fix_above

logger = logging.getLogger(__name__)

CHUNK = 500


@dataclass(frozen=True)
class AdvisoryInfo:
    advisory_id: str
    kind: str
    summary: str | None
    severity: str | None
    cvss_score: float | None
    kev: bool
    epss: float | None
    cves: tuple[str, ...]


@dataclass(frozen=True)
class Match:
    component: Component
    advisory: AdvisoryInfo
    record_ids: tuple[str, ...]
    fixed_version: str | None


@dataclass
class _Hit:
    component: Component
    records: set[str] = field(default_factory=set)
    fixed: set[str] = field(default_factory=set)


@dataclass
class MatchStats:
    components: int = 0
    unsupported: int = 0  # 照合できないエコシステム
    unevaluable: int = 0  # 範囲を評価できなかった (バージョンの形式が違う等) 組み合わせ
    by_ecosystem: dict[str, int] = field(default_factory=dict)


class Matcher:
    def __init__(self, intel_engine: Engine) -> None:
        self._intel = intel_engine
        self._pypi_names: dict[str, list[str]] | None = None

    def _osv_names(self, comp: Component) -> list[str]:
        if comp.ecosystem != "PyPI":
            return [comp.name]
        if self._pypi_names is None:
            with self._intel.connect() as conn:
                rows = conn.execute(
                    text("SELECT DISTINCT name FROM v_advisory_affected WHERE ecosystem = 'PyPI'")
                ).scalars().all()
            names: dict[str, list[str]] = defaultdict(list)
            for n in rows:
                if n:
                    names[canonical_pypi_name(n)].append(n)
            self._pypi_names = dict(names)
        return self._pypi_names.get(canonical_pypi_name(comp.name), [])

    def _affected_rows(self, ecosystem: str, names: list[str]) -> list[tuple]:
        stmt = text(
            "SELECT advisory_id, record_id, name, ranges_json, fixed_json, versions_json "
            "FROM v_advisory_affected WHERE ecosystem = :e AND name IN :names"
        ).bindparams(bindparam("names", expanding=True))
        rows: list[tuple] = []
        with self._intel.connect() as conn:
            for i in range(0, len(names), CHUNK):
                rows += [tuple(r) for r in conn.execute(stmt, {"e": ecosystem, "names": names[i:i + CHUNK]})]
        return rows

    def _advisories(self, ids: list[str]) -> dict[str, AdvisoryInfo]:
        stmt = text(
            "SELECT advisory_id, kind, summary, severity, cvss_score, kev, epss, cves_json, withdrawn "
            "FROM v_advisories WHERE advisory_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        out: dict[str, AdvisoryInfo] = {}
        with self._intel.connect() as conn:
            for i in range(0, len(ids), CHUNK):
                for r in conn.execute(stmt, {"ids": ids[i:i + CHUNK]}):
                    if r[8]:
                        continue  # 取り下げ済み
                    out[r[0]] = AdvisoryInfo(
                        r[0], r[1], r[2], r[3], r[4], bool(r[5]), r[6], tuple(json.loads(r[7] or "[]"))
                    )
        return out

    def match(self, components: list[Component]) -> tuple[list[Match], MatchStats]:
        stats = MatchStats(components=len(components))
        by_eco: dict[str, list[Component]] = defaultdict(list)
        for c in components:
            if c.ecosystem not in SUPPORTED_ECOSYSTEMS:
                stats.unsupported += 1
                continue
            by_eco[c.ecosystem].append(c)
        hits: dict[tuple[str, str], _Hit] = {}
        for eco, comps in by_eco.items():
            osv_names = {c.purl: self._osv_names(c) for c in comps}
            rows = self._affected_rows(eco, sorted({n for ns in osv_names.values() for n in ns}))
            by_name: dict[str, list[tuple]] = defaultdict(list)
            for row in rows:
                by_name[row[2]].append(row)
            for c in comps:
                for name in osv_names[c.purl]:
                    for adv_id, rec_id, _, ranges, fixed, versions in by_name[name]:
                        result = is_affected(eco, c.version, json.loads(ranges), json.loads(versions or "[]"))
                        if result is None:
                            stats.unevaluable += 1
                            continue
                        if not result:
                            continue
                        hit = hits.setdefault((c.purl, adv_id), _Hit(c))
                        hit.records.add(rec_id)
                        hit.fixed.update(json.loads(fixed))
            stats.by_ecosystem[eco] = len(comps)
        advisories = self._advisories(sorted({adv for _, adv in hits}))
        matches = []
        for (_, adv_id), hit in sorted(hits.items()):
            if adv_id not in advisories:
                continue
            c = hit.component
            matches.append(Match(
                c, advisories[adv_id], tuple(sorted(hit.records)),
                smallest_fix_above(c.ecosystem, c.version, sorted(hit.fixed)),
            ))
        if stats.unevaluable:
            logger.info("unevaluable affected ranges: %d", stats.unevaluable)
        return matches, stats
