"""OSV レコードを Advisory にまとめる規則 (メモ FR-I04: CVE 番号で名寄せ)。

- CVE がちょうど 1 つ: その CVE 番号を advisory_id にする (GHSA / PYSEC / DEBIAN-CVE 等が合流)
- CVE が 2 つ以上: 複数の CVE をまとめた告知 (USN / DSA / RHSA 等)。連鎖的な合流を
  避けるため、自分の ID で独立した Advisory にする。KEV・EPSS は含む CVE で引く
- CVE が無い: エイリアス先の既存レコード (まとめ告知を除く) の Advisory に合流し、
  無ければ自分の ID を使う (例: CVE 未採番の GHSA と PYSEC)
"""
from __future__ import annotations

from collections.abc import Callable

from .osv_record import OsvRecord


def resolve_advisory_id(
    record: OsvRecord, lookup_alias: Callable[[str], str | None]
) -> str:
    """``lookup_alias(alias)`` はそのエイリアスを ID に持つ既存レコードの advisory_id を返す。"""
    cves = sorted(record.cves)
    if len(cves) == 1:
        return cves[0]
    if len(cves) > 1:
        return record.record_id
    for alias in record.aliases:
        target = lookup_alias(alias)
        if target:
            return target
    return record.record_id
