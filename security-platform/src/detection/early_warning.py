"""L4 の早期警告: 照合に使わない記事の主張 (未確認など) と、使っているパッケージの名前の完全一致 (要件 R12)。

intel.db の v_report_claims (読み取り契約) から、Advisory にしていない主張 (status が unconfirmed、または
confirmed でも版が無いなどで照合できないもの) を読み、今回の照合の部品とエコシステム・名前で突き合わせる。
版は見ない (記事の版の書き方はまちまちで、名前の一致だけで知らせる価値がある)。通知に版の一致の有無を添える。

Finding にはしない (優先度・期限・Issue の対象外)。新しく当たったら warning.opened を出し、notify が
「未確認情報」として LINE で送る。当たらなくなったら closed にする (知らせない)。
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import OperationalError

from ..common.events import Outbox
from ..common.timeutil import to_iso
from ..intel.claims import name_key, osv_ecosystem
from .lockfiles import Component

EVENT_WARNING_OPENED = "warning.opened"
STATUSES = ("unconfirmed", "confirmed")
KIND_HOST_HISTORY = "host_history"


@dataclass(frozen=True)
class Claim:
    claim_id: str
    report_id: str
    ecosystem: str  # OSV の表記
    package: str
    versions: tuple[str, ...]
    kind: str
    quote: str
    status: str
    feed_id: str
    trust: str
    title: str
    url: str | None


@dataclass(frozen=True)
class EarlyWarning:
    service_id: str
    component: Component
    source_kind: str
    claim: Claim

    @property
    def warning_id(self) -> str:
        key = "\n".join((self.claim.report_id, self.claim.ecosystem, name_key(self.claim.ecosystem, self.claim.package),
                         self.service_id, self.component.purl))
        return "wrn_" + hashlib.sha256(key.encode()).hexdigest()[:20]

    def evidence(self) -> dict[str, Any]:
        c, comp = self.claim, self.component
        return {
            "ecosystem": comp.ecosystem, "package": comp.name, "version": comp.version,
            "source_kind": self.source_kind, "kind": c.kind, "status": c.status,
            "claim_versions": list(c.versions), "version_matched": comp.version in c.versions,
            "quote": c.quote, "feed_id": c.feed_id, "trust": c.trust, "title": c.title, "url": c.url,
        }


def load_claims(intel: Engine) -> list[Claim]:
    """intel.db が L4 より前 (v_report_claims が無い) なら空。"""
    try:
        with intel.connect() as conn:
            rows = conn.execute(text(
                "SELECT claim_id, report_id, ecosystem, package, versions_json, kind, quote, status, feed_id, trust, "
                "title, url FROM v_report_claims WHERE status IN (:u, :c) AND advisory_id IS NULL "
                "ORDER BY first_seen_at, claim_id"
            ), {"u": STATUSES[0], "c": STATUSES[1]}).all()
    except OperationalError:
        return []
    out = []
    for r in rows:
        eco = osv_ecosystem(r[2])
        if eco is not None:
            out.append(Claim(r[0], r[1], eco, r[3], tuple(json.loads(r[4])), r[5], r[6], r[7], r[8], r[9],
                             r[10], r[11]))
    return out


def find(claims: list[Claim], components: list[tuple[str, Component, str]]) -> dict[str, EarlyWarning]:
    """components: (service_id, 部品, 見つかった元の種類)。過去に入っていた版は悪性・侵害の主張とだけ突き合わせる。"""
    by_name: dict[tuple[str, str], list[tuple[str, Component, str]]] = defaultdict(list)
    for svc, comp, kind in components:
        by_name[(comp.ecosystem, name_key(comp.ecosystem, comp.name))].append((svc, comp, kind))
    out: dict[str, EarlyWarning] = {}
    for c in claims:
        for svc, comp, kind in by_name.get((c.ecosystem, name_key(c.ecosystem, c.package)), []):
            if kind == KIND_HOST_HISTORY and c.kind == "vulnerable":
                continue
            w = EarlyWarning(svc, comp, kind, c)
            out.setdefault(w.warning_id, w)
    return out


def reconcile(conn: Connection, outbox: Outbox, desired: dict[str, EarlyWarning], incomplete: set[str],
              now: datetime) -> tuple[int, int]:
    """(新しく当たった数, 閉じた数)。照合が欠けたサービスの警告は閉じない。"""
    existing = {r[0]: (r[1], r[2]) for r in conn.execute(
        text("SELECT warning_id, state, service_id FROM early_warnings")).all()}
    opened = closed = 0
    t = to_iso(now)
    for wid, w in desired.items():
        ev = json.dumps(w.evidence(), ensure_ascii=False, sort_keys=True)
        state = existing.get(wid, (None, None))[0]
        if state is None:
            conn.execute(text("""
                INSERT INTO early_warnings (warning_id, service_id, purl, report_id, claim_id, state, evidence_json,
                  first_seen_at, updated_at)
                VALUES (:id, :s, :p, :r, :c, 'open', :ev, :t, :t)
            """), {"id": wid, "s": w.service_id, "p": w.component.purl, "r": w.claim.report_id,
                   "c": w.claim.claim_id, "ev": ev, "t": t})
        else:
            conn.execute(text(
                "UPDATE early_warnings SET claim_id = :c, state = 'open', evidence_json = :ev, updated_at = :t, "
                "closed_at = NULL WHERE warning_id = :id"
            ), {"id": wid, "c": w.claim.claim_id, "ev": ev, "t": t})
        if state != "open":
            outbox.publish(conn, EVENT_WARNING_OPENED, {"warning_id": wid, "service_id": w.service_id,
                                                        "purl": w.component.purl, **w.evidence()})
            opened += 1
    for wid, (state, service_id) in existing.items():
        if wid not in desired and state == "open" and service_id not in incomplete:
            conn.execute(text("UPDATE early_warnings SET state = 'closed', closed_at = :t, updated_at = :t "
                              "WHERE warning_id = :id"), {"id": wid, "t": t})
            closed += 1
    return opened, closed
