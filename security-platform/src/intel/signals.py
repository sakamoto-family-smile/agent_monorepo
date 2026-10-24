"""KEV と EPSS (CVE 単位の補助シグナル) の取り込み。

どちらも advisories 行には持たず、v_advisories で都度結合する。ここでは取り込みと、
イベントにすべき変化 (KEV 掲載・削除、EPSS の大きな上昇) の検出だけを行う。
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import Connection, text

from ..common.timeutil import utc_now_iso
from .changes import RunContext


@dataclass(frozen=True)
class KevEntry:
    cve: str
    vendor: str | None
    product: str | None
    name: str | None
    date_added: str | None
    due_date: str | None
    ransomware: str | None
    short_description: str | None


@dataclass(frozen=True)
class EpssScore:
    cve: str
    epss: float
    percentile: float


def _advisories_for(conn: Connection, cve: str) -> list[str]:
    return conn.execute(
        text("SELECT advisory_id FROM advisory_cves WHERE cve = :c"), {"c": cve}
    ).scalars().all()


KEV_MIN_RATIO = 0.5  # 既存件数に対してこれを下回るスナップショットは壊れているとみなす


def upsert_kev(conn: Connection, ctx: RunContext, entries: list[KevEntry], raw_ref: str) -> set[str]:
    """KEV の全件スナップショットを反映し、再集計が必要な advisory_id を返す。"""
    existing = set(conn.execute(text("SELECT cve FROM kev_entries")).scalars())
    incoming = {e.cve for e in entries}
    if existing and len(incoming) < len(existing) * KEV_MIN_RATIO:
        raise ValueError(
            f"KEV snapshot too small ({len(incoming)} < {KEV_MIN_RATIO:.0%} of {len(existing)}); refusing"
        )
    now = utc_now_iso()
    if entries:
        _write_kev(conn, entries, raw_ref, now)
    removed = existing - incoming
    for cve in removed:
        conn.execute(text("DELETE FROM kev_entries WHERE cve = :c"), {"c": cve})
    touched: set[str] = set()
    for cve, change in [*((c, "kev_added") for c in incoming - existing),
                        *((c, "kev_removed") for c in removed)]:
        targets = _advisories_for(conn, cve) or [cve]  # 未登録なら KEV だけの Advisory を作る
        for advisory_id in targets:
            ctx.add_signal(advisory_id, change)
            touched.add(advisory_id)
    return touched


def _write_kev(conn: Connection, entries: list[KevEntry], raw_ref: str, now: str) -> None:
    conn.execute(
        text(
            """
            INSERT INTO kev_entries (cve, vendor, product, name, date_added, due_date, ransomware,
              short_description, raw_ref, updated_at)
            VALUES (:cve, :vendor, :product, :name, :date_added, :due_date, :ransomware,
              :short_description, :raw_ref, :now)
            ON CONFLICT(cve) DO UPDATE SET vendor = excluded.vendor, product = excluded.product,
              name = excluded.name, date_added = excluded.date_added, due_date = excluded.due_date,
              ransomware = excluded.ransomware, short_description = excluded.short_description,
              raw_ref = excluded.raw_ref, updated_at = excluded.updated_at
            """
        ),
        [{**e.__dict__, "raw_ref": raw_ref, "now": now} for e in entries],
    )


def upsert_epss(
    conn: Connection, ctx: RunContext, scores: Iterable[EpssScore], score_date: str | None,
    delta: float,
) -> int:
    """EPSS を反映し、``delta`` 以上上がった CVE を持つ Advisory にシグナルを積む。"""
    now = utc_now_iso()
    conn.execute(text("CREATE TEMP TABLE IF NOT EXISTS epss_in (cve TEXT PRIMARY KEY, epss REAL, percentile REAL)"))
    conn.execute(text("DELETE FROM epss_in"))
    batch: list[dict[str, object]] = []
    count = 0
    for s in scores:
        batch.append({"c": s.cve, "e": s.epss, "p": s.percentile})
        if len(batch) >= 5000:
            conn.execute(text("INSERT OR REPLACE INTO epss_in VALUES (:c, :e, :p)"), batch)
            count += len(batch)
            batch = []
    if batch:
        conn.execute(text("INSERT OR REPLACE INTO epss_in VALUES (:c, :e, :p)"), batch)
        count += len(batch)
    risen = conn.execute(
        text("SELECT DISTINCT c.advisory_id FROM epss_in i JOIN epss_scores s ON s.cve = i.cve "
             "JOIN advisory_cves c ON c.cve = i.cve WHERE i.epss - s.epss >= :d"),
        {"d": delta},
    ).scalars().all()
    for advisory_id in risen:
        ctx.add_signal(advisory_id, "epss_increased")
    conn.execute(
        text("INSERT INTO epss_scores (cve, epss, percentile, score_date, updated_at) "
             "SELECT cve, epss, percentile, :sd, :now FROM epss_in WHERE true "
             "ON CONFLICT(cve) DO UPDATE SET epss = excluded.epss, percentile = excluded.percentile, "
             "score_date = excluded.score_date, updated_at = excluded.updated_at"),
        {"sd": score_date, "now": now},
    )
    conn.execute(text("DROP TABLE epss_in"))
    return count
