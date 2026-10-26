"""Advisory の再集計。

advisories の行は osv_records (と KEV) からいつでも作り直せる集約値で、手で更新しない。
KEV・EPSS は v_advisories ビューで都度結合するため、ここでは扱わない
(KEV だけに載っている CVE の Advisory を作るときを除く)。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from sqlalchemy import Connection, text

from ..common.timeutil import utc_now_iso
from .osv_record import is_cve

SUMMARY_PREFERENCE = ("GHSA", "PYSEC", "GO", "RUSTSEC", "CVE")
SEVERITY_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "MODERATE": 2, "LOW": 1}
# OSV の malicious-packages (MAL-) は脆弱性ではなく悪性パッケージの報告で、CVSS を持たない
MALICIOUS_PREFIX = "MAL-"


@dataclass(frozen=True)
class AdvisoryState:
    advisory_id: str
    cves: tuple[str, ...]
    summary: str | None
    cvss_score: float | None
    cvss_vector: str | None
    severity: str | None
    published_at: str | None
    modified_at: str | None
    withdrawn: bool
    record_count: int
    affected_hash: str
    fixed_hash: str
    affected_purls: tuple[str, ...]
    kind: str = "vulnerability"  # vulnerability / malicious

    def comparable(self) -> dict[str, object]:
        """変化検知と履歴に残す値 (affected_purls は件数が多いので除く。kind は分類なので除く)。"""
        d = asdict(self)
        d.pop("affected_purls")
        d.pop("kind")
        d["cves"] = list(self.cves)
        return d


def severity_from_score(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    return "LOW" if score > 0 else None


def _digest(items: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(items)).encode()).hexdigest()[:16]


def _pick_summary(rows: list[tuple[str, str | None]]) -> str | None:
    by_prefix = {p: s for p, s in rows if s}
    for prefix in SUMMARY_PREFERENCE:
        if prefix in by_prefix:
            return by_prefix[prefix]
    return next((s for _, s in rows if s), None)


def _max_label(labels: list[str | None]) -> str | None:
    known = [lbl.upper() for lbl in labels if lbl and lbl.upper() in SEVERITY_ORDER]
    if not known:
        return None
    top = max(known, key=SEVERITY_ORDER.__getitem__)
    return "MEDIUM" if top == "MODERATE" else top


def _from_records(conn: Connection, advisory_id: str) -> AdvisoryState | None:
    recs = conn.execute(
        text(
            "SELECT record_id, db_prefix, summary, cvss_score, cvss_vector, severity_label, "
            "withdrawn, published_at, modified_at FROM osv_records WHERE advisory_id = :a"
        ),
        {"a": advisory_id},
    ).all()
    if not recs:
        return None
    ids = [r[0] for r in recs]
    aliases = conn.execute(
        text("SELECT x.alias FROM record_aliases x JOIN osv_records r ON r.record_id = x.record_id "
             "WHERE r.advisory_id = :a"),
        {"a": advisory_id},
    ).scalars().all()
    cves = sorted({i for i in [*ids, *aliases, advisory_id] if is_cve(i)})
    affected = conn.execute(
        text("SELECT f.ecosystem, f.name, f.purl, f.ranges_json, f.fixed_json FROM record_affected f "
             "JOIN osv_records r ON r.record_id = f.record_id WHERE r.advisory_id = :a"),
        {"a": advisory_id},
    ).all()
    pkgs = sorted({purl or f"{eco}:{name}" for eco, name, purl, _, _ in affected})
    fixed = [f"{eco}:{name}@{v}" for eco, name, _, _, fx in affected for v in json.loads(fx)]
    scored = [(r[3], r[4]) for r in recs if r[3] is not None]
    score, vector = max(scored, key=lambda t: t[0]) if scored else (None, None)
    published = [r[7] for r in recs if r[7]]
    modified = [r[8] for r in recs if r[8]]
    return AdvisoryState(
        advisory_id=advisory_id,
        cves=tuple(cves),
        summary=_pick_summary([(r[1], r[2]) for r in recs]),
        cvss_score=score,
        cvss_vector=vector,
        severity=severity_from_score(score) or _max_label([r[5] for r in recs]),
        published_at=min(published) if published else None,
        modified_at=max(modified) if modified else None,
        withdrawn=all(bool(r[6]) for r in recs),
        record_count=len(recs),
        affected_hash=_digest([f"{eco}:{name}:{rng}" for eco, name, _, rng, _ in affected]),
        fixed_hash=_digest(fixed),
        affected_purls=tuple(pkgs),
        kind="malicious" if any(i.startswith(MALICIOUS_PREFIX) for i in ids) else "vulnerability",
    )


def _from_kev(conn: Connection, advisory_id: str) -> AdvisoryState | None:
    """OSV に載っておらず KEV だけにある CVE (主に製品の脆弱性) の Advisory。"""
    if not is_cve(advisory_id):
        return None
    row = conn.execute(
        text("SELECT name, date_added FROM kev_entries WHERE cve = :c"), {"c": advisory_id}
    ).first()
    if row is None:
        return None
    return AdvisoryState(
        advisory_id, (advisory_id,), row[0], None, None, None, row[1], row[1], False, 0,
        _digest([]), _digest([]), (),
    )


def compute_state(conn: Connection, advisory_id: str) -> AdvisoryState | None:
    return _from_records(conn, advisory_id) or _from_kev(conn, advisory_id)


def load_state(conn: Connection, advisory_id: str) -> dict[str, object] | None:
    row = conn.execute(
        text("SELECT advisory_id, cves_json, summary, cvss_score, cvss_vector, severity, "
             "published_at, modified_at, withdrawn, record_count, affected_hash, fixed_hash "
             "FROM advisories WHERE advisory_id = :a"),
        {"a": advisory_id},
    ).first()
    if row is None:
        return None
    return {
        "advisory_id": row[0], "cves": json.loads(row[1]), "summary": row[2],
        "cvss_score": row[3], "cvss_vector": row[4], "severity": row[5],
        "published_at": row[6], "modified_at": row[7], "withdrawn": bool(row[8]),
        "record_count": row[9], "affected_hash": row[10], "fixed_hash": row[11],
    }


def save_state(conn: Connection, state: AdvisoryState) -> None:
    now = utc_now_iso()
    conn.execute(
        text(
            """
            INSERT INTO advisories (advisory_id, kind, cves_json, summary, cvss_score, cvss_vector,
              severity, published_at, modified_at, withdrawn, record_count, affected_hash,
              fixed_hash, first_seen_at, updated_at)
            VALUES (:advisory_id, :kind, :cves, :summary, :cvss_score, :cvss_vector,
              :severity, :published_at, :modified_at, :withdrawn, :record_count, :affected_hash,
              :fixed_hash, :now, :now)
            ON CONFLICT(advisory_id) DO UPDATE SET kind = excluded.kind, cves_json = excluded.cves_json,
              summary = excluded.summary, cvss_score = excluded.cvss_score,
              cvss_vector = excluded.cvss_vector, severity = excluded.severity,
              published_at = excluded.published_at, modified_at = excluded.modified_at,
              withdrawn = excluded.withdrawn, record_count = excluded.record_count,
              affected_hash = excluded.affected_hash, fixed_hash = excluded.fixed_hash,
              updated_at = excluded.updated_at
            """
        ),
        {**state.comparable(), "kind": state.kind, "cves": json.dumps(list(state.cves)), "now": now},
    )
    conn.execute(text("DELETE FROM advisory_cves WHERE advisory_id = :a"), {"a": state.advisory_id})
    if state.cves:
        conn.execute(
            text("INSERT INTO advisory_cves (advisory_id, cve) VALUES (:a, :c)"),
            [{"a": state.advisory_id, "c": c} for c in state.cves],
        )


def delete_state(conn: Connection, advisory_id: str) -> None:
    conn.execute(text("DELETE FROM advisory_cves WHERE advisory_id = :a"), {"a": advisory_id})
    conn.execute(text("DELETE FROM advisories WHERE advisory_id = :a"), {"a": advisory_id})
