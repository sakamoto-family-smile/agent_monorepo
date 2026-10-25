"""osv_records / record_aliases / record_affected の書き込み。

再集計が必要な advisory_id は同じトランザクションで ``advisories_dirty`` に積む。
途中で落ちても次の実行で再集計されるので、変化 (とイベント) を取りこぼさない。
内容ハッシュが同じレコードは何もしない。
"""
from __future__ import annotations

import json

from sqlalchemy import Connection, bindparam, text

from ..common.timeutil import utc_now_iso
from .grouping import resolve_advisory_id
from .osv_record import OsvRecord, is_cve


def _lookup_alias(conn: Connection, alias: str) -> str | None:
    """エイリアス先レコードの advisory_id。まとめ告知 (複数 CVE) には合流しない。"""
    row = conn.execute(
        text("SELECT advisory_id FROM osv_records WHERE record_id = :id"), {"id": alias}
    ).first()
    if row is None:
        return None
    target_aliases = conn.execute(
        text("SELECT alias FROM record_aliases WHERE record_id = :id"), {"id": alias}
    ).scalars()
    cves = {a for a in target_aliases if is_cve(a)} | ({alias} if is_cve(alias) else set())
    return None if len(cves) > 1 else row[0]


def _stored_record(conn: Connection, record_id: str) -> OsvRecord | None:
    """再キー計算に必要な最小限の情報だけを DB から復元する。"""
    row = conn.execute(
        text("SELECT record_id FROM osv_records WHERE record_id = :id"), {"id": record_id}
    ).first()
    if row is None:
        return None
    rows = conn.execute(
        text("SELECT alias, relation FROM record_aliases WHERE record_id = :id"), {"id": record_id}
    ).all()
    aliases = tuple(sorted(a for a, rel in rows if rel == "alias"))
    upstream = tuple(sorted(a for a, rel in rows if rel == "upstream"))
    return OsvRecord(record_id, aliases, upstream, None, None, None, False, None, None, None, (), "")


def _write_record(
    conn: Connection, rec: OsvRecord, advisory_id: str, raw_ref: str, *, is_new: bool
) -> None:
    now = utc_now_iso()
    conn.execute(
        text(
            """
            INSERT INTO osv_records (record_id, advisory_id, db_prefix, summary, cvss_vector,
              cvss_score, severity_label, withdrawn, published_at, modified_at, content_hash,
              raw_ref, ingested_at, updated_at)
            VALUES (:record_id, :advisory_id, :db_prefix, :summary, :cvss_vector, :cvss_score,
              :severity_label, :withdrawn, :published_at, :modified_at, :content_hash, :raw_ref,
              :now, :now)
            ON CONFLICT(record_id) DO UPDATE SET advisory_id = excluded.advisory_id,
              db_prefix = excluded.db_prefix, summary = excluded.summary,
              cvss_vector = excluded.cvss_vector, cvss_score = excluded.cvss_score,
              severity_label = excluded.severity_label, withdrawn = excluded.withdrawn,
              published_at = excluded.published_at, modified_at = excluded.modified_at,
              content_hash = excluded.content_hash, raw_ref = excluded.raw_ref,
              updated_at = excluded.updated_at
            """
        ),
        {
            "record_id": rec.record_id,
            "advisory_id": advisory_id,
            "db_prefix": rec.db_prefix,
            "summary": rec.summary,
            "cvss_vector": rec.cvss_vector,
            "cvss_score": rec.cvss_score,
            "severity_label": rec.severity_label,
            "withdrawn": rec.withdrawn,
            "published_at": rec.published_at,
            "modified_at": rec.modified_at,
            "content_hash": rec.content_hash,
            "raw_ref": raw_ref,
            "now": now,
        },
    )
    if not is_new:
        params = {"id": rec.record_id}
        conn.execute(text("DELETE FROM record_aliases WHERE record_id = :id"), params)
        conn.execute(text("DELETE FROM record_affected WHERE record_id = :id"), params)
    alias_rows = [{"id": rec.record_id, "alias": a, "rel": "alias"} for a in rec.aliases]
    alias_rows += [
        {"id": rec.record_id, "alias": a, "rel": "upstream"}
        for a in rec.upstream
        if a not in rec.aliases
    ]
    if alias_rows:
        conn.execute(
            text("INSERT INTO record_aliases (record_id, alias, relation) VALUES (:id, :alias, :rel)"),
            alias_rows,
        )
    affected_rows = [
        {
            "id": rec.record_id,
            "idx": i,
            "ecosystem": a.ecosystem,
            "name": a.name,
            "purl": a.purl,
            "ranges": json.dumps(a.ranges, sort_keys=True),
            "fixed": json.dumps(a.fixed),
            "vc": a.versions_count,
        }
        for i, a in enumerate(rec.affected)
    ]
    if affected_rows:
        conn.execute(
            text(
                "INSERT INTO record_affected (record_id, idx, ecosystem, name, purl, ranges_json, "
                "fixed_json, versions_count) VALUES (:id, :idx, :ecosystem, :name, :purl, "
                ":ranges, :fixed, :vc)"
            ),
            affected_rows,
        )


def _rekey_dependents(conn: Connection, record_id: str) -> set[str]:
    """``record_id`` をエイリアスに持つレコードの advisory_id を付け直す。

    付け直したレコードをさらにエイリアスに持つレコードへも辿る (A → B → C の連鎖で、
    C が CVE を得たら A まで届かせる)。キーが変わらなかったレコードの先は辿らない。
    """
    touched: set[str] = set()
    queue = [record_id]
    seen = {record_id}
    while queue:
        target = queue.pop(0)
        deps = conn.execute(
            text("SELECT DISTINCT record_id FROM record_aliases WHERE alias = :id AND record_id != :id"),
            {"id": target},
        ).scalars().all()
        for dep_id in deps:
            if dep_id in seen:
                continue
            seen.add(dep_id)
            dep = _stored_record(conn, dep_id)
            if dep is None:
                continue
            current = conn.execute(
                text("SELECT advisory_id FROM osv_records WHERE record_id = :id"), {"id": dep_id}
            ).scalar_one()
            new_key = resolve_advisory_id(dep, lambda a: _lookup_alias(conn, a))
            if new_key != current:
                conn.execute(
                    text("UPDATE osv_records SET advisory_id = :k, updated_at = :u WHERE record_id = :id"),
                    {"k": new_key, "u": utc_now_iso(), "id": dep_id},
                )
                touched |= {current, new_key}
                queue.append(dep_id)
    return touched


def mark_dirty(conn: Connection, advisory_ids: set[str]) -> None:
    if advisory_ids:
        conn.execute(
            text("INSERT OR IGNORE INTO advisories_dirty (advisory_id) VALUES (:a)"),
            [{"a": a} for a in sorted(advisory_ids)],
        )


def existing_hashes(conn: Connection, record_ids: list[str]) -> dict[str, tuple[str, str]]:
    """record_id → (advisory_id, content_hash)。バッチ単位で 1 回だけ引く。"""
    out: dict[str, tuple[str, str]] = {}
    for i in range(0, len(record_ids), 500):
        rows = conn.execute(
            text("SELECT record_id, advisory_id, content_hash FROM osv_records "
                 "WHERE record_id IN :ids").bindparams(bindparam("ids", expanding=True)),
            {"ids": record_ids[i : i + 500]},
        ).all()
        out.update({r[0]: (r[1], r[2]) for r in rows})
    return out


def upsert_osv_record(
    conn: Connection, rec: OsvRecord, raw_ref: str, old: tuple[str, str] | None
) -> set[str]:
    """``old`` は existing_hashes() の結果 (無ければ None)。再集計対象を返し、dirty にも積む。"""
    if old is not None and old[1] == rec.content_hash:
        return set()
    advisory_id = resolve_advisory_id(rec, lambda a: _lookup_alias(conn, a))
    _write_record(conn, rec, advisory_id, raw_ref, is_new=old is None)
    touched = {advisory_id}
    if old is not None:
        touched.add(old[0])
    touched |= _rekey_dependents(conn, rec.record_id)
    mark_dirty(conn, touched)
    return touched
