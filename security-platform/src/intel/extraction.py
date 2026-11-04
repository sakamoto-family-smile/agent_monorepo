"""L4: 記事を extractor に渡し、抜き出した結果を原文と突き合わせて report_claims に取り込む (intel の extract ジョブ)。

1. 取り込み: data/llm/out/ の結果を読み、主張ごとに grounding (src/llm/grounding.py) を通して保存する。
   失敗した記事は MAX_ATTEMPTS 回までやり直す (in/ のファイルを残せば extractor が次の夜に拾う)
2. 依頼: まだ抽出していない記事を前段で絞り込み、data/llm/in/ に書く
   - 初回の取得で既にあった記事 (initial = 1) は対象にしない (古い記事に Max プランの枠を使わない)
   - 脆弱性・悪性パッケージの語を含まない記事は skipped にする
   - extractor 待ちは MAX_PENDING 件まで
3. 揃える: in/ のファイルを queued の記事と一致させる (古い依頼に LLM の枠を使わない)
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, Engine, bindparam, text

from ..llm.exchange import JobResult, job_id, list_ids, read_result, write_job
from ..llm.grounding import ground
from ..llm.schema import ExtractInput, validate_output

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
MAX_PENDING = 200
SCAN_LIMIT = 1000  # 1 回に絞り込みにかける記事の数
TRUSTS = ("official", "research")  # news は誤報の多さを見てから (L4 の方針)

PREFILTER = re.compile(
    r"malicious|malware|compromis|backdoor|typosquat|supply[- ]?chain|vulnerab|exploit|cve-\d{4}-\d+|ghsa-"
    r"|security (?:advisory|update|release|fix|bulletin)|credential|stealer|\bworm\b|hijack|takeover|trojan"
    r"|脆弱性|不正|マルウェア|侵害|悪性|悪意|注意喚起|攻撃|乗っ取",
    re.IGNORECASE,
)


@dataclass
class ExtractResult:
    queued: int = 0
    skipped: int = 0
    ingested: int = 0
    failed: int = 0
    retried: int = 0
    claims: int = 0
    grounded: int = 0


def source_text(title: str, summary: str) -> str:
    """LLM に渡す本文と、grounding で突き合わせる原文 (同じものを使う)。"""
    return f"{title}\n{summary}"


def _claim_id(report_id: str, content_hash: str, idx: int) -> str:
    return "clm_" + hashlib.sha256(f"{report_id}\n{content_hash}\n{idx}".encode()).hexdigest()[:24]


def _remove(dirs: tuple[Path, Path], jid: str) -> None:
    for d in dirs:
        (d / f"{jid}.json").unlink(missing_ok=True)


# ── 取り込み ──────────────────────────────────────────────────────────────
def _store(conn: Connection, row: dict, r: JobResult, out: dict, now: str, result: ExtractResult) -> None:
    rid, h = row["report_id"], row["content_hash"]
    conn.execute(text("DELETE FROM report_claims WHERE report_id = :r"), {"r": rid})
    grounded = 0
    for idx, c in enumerate(out["claims"]):
        g = ground(source_text(row["title"], row["summary"]), c)
        grounded += g.grounded
        conn.execute(text("""
            INSERT INTO report_claims (claim_id, report_id, content_hash, idx, ecosystem, package, versions_json,
              kind, identifiers_json, quote, grounded, notes_json, provider, model, prompt_version, extracted_at)
            VALUES (:id, :r, :h, :i, :eco, :pkg, :v, :kind, :ids, :q, :g, :notes, :p, :m, :pv, :t)
        """), {"id": _claim_id(rid, h, idx), "r": rid, "h": h, "i": idx, "eco": g.ecosystem, "pkg": g.package,
               "v": json.dumps(g.versions, ensure_ascii=False), "kind": g.kind,
               "ids": json.dumps(g.identifiers), "q": g.quote, "g": g.grounded,
               "notes": json.dumps(g.notes, ensure_ascii=False), "p": r.provider, "m": r.model,
               "pv": r.prompt_version, "t": r.finished_at})
    conn.execute(text("""
        UPDATE report_extractions SET status = 'done', provider = :p, model = :m, prompt_version = :pv,
          about_specific_packages = :about, claims = :n, grounded_claims = :g, error = NULL, finished_at = :t,
          updated_at = :now
        WHERE report_id = :r
    """), {"p": r.provider, "m": r.model, "pv": r.prompt_version, "about": out["about_specific_packages"],
           "n": len(out["claims"]), "g": grounded, "t": r.finished_at, "now": now, "r": rid})
    result.claims += len(out["claims"])
    result.grounded += grounded


def ingest(engine: Engine, in_dir: Path, out_dir: Path, now: str) -> ExtractResult:
    result = ExtractResult()
    for jid in list_ids(out_dir):
        try:
            r = read_result(out_dir, jid)
        except (ValueError, KeyError, OSError) as e:
            logger.warning("drop unreadable result %s: %s", jid, e)
            (out_dir / f"{jid}.json").unlink(missing_ok=True)
            continue
        with engine.begin() as conn:
            row = conn.execute(text("""
                SELECT e.report_id, e.content_hash, e.attempts, r.title, r.summary FROM report_extractions e
                JOIN reports r ON r.report_id = e.report_id AND r.content_hash = e.content_hash
                WHERE e.job_id = :j AND e.status = 'queued'
            """), {"j": jid}).mappings().first()
            if row is None:  # 記事が更新されて別の job になった、など
                _remove((in_dir, out_dir), jid)
                continue
            error = r.error
            if error is None:
                try:
                    out = validate_output(r.output)
                except ValueError as e:
                    error = f"invalid output: {e}"
            if error is None:
                _store(conn, dict(row), r, out, now, result)
                result.ingested += 1
                _remove((in_dir, out_dir), jid)
                continue
            attempts = row["attempts"] + 1
            final = attempts >= MAX_ATTEMPTS
            conn.execute(text("""
                UPDATE report_extractions SET attempts = :a, error = :e, provider = :p, model = :m,
                  status = CASE WHEN :final THEN 'failed' ELSE status END,
                  finished_at = CASE WHEN :final THEN :t ELSE finished_at END, updated_at = :now
                WHERE report_id = :r
            """), {"a": attempts, "e": error[:1000], "p": r.provider, "m": r.model, "final": final,
                   "t": r.finished_at, "now": now, "r": row["report_id"]})
            if final:
                result.failed += 1
                _remove((in_dir, out_dir), jid)
            else:  # in/ を残して out/ だけ消すと、extractor が次の夜にやり直す
                result.retried += 1
                (out_dir / f"{jid}.json").unlink(missing_ok=True)
    return result


# ── 依頼 ──────────────────────────────────────────────────────────────────
def queue(engine: Engine, in_dir: Path, now: str, result: ExtractResult, max_pending: int = MAX_PENDING) -> None:
    with engine.begin() as conn:
        pending = conn.execute(text("SELECT COUNT(*) FROM report_extractions WHERE status = 'queued'")).scalar_one()
        rows = conn.execute(text("""
            SELECT r.report_id, r.content_hash, r.title, r.summary, r.url FROM reports r
            LEFT JOIN report_extractions e ON e.report_id = r.report_id
            WHERE r.initial = 0 AND r.trust IN :trusts
              AND (e.report_id IS NULL OR e.content_hash != r.content_hash)
            ORDER BY r.first_seen_at, r.report_id
            LIMIT :n
        """).bindparams(bindparam("trusts", expanding=True)),
            {"n": SCAN_LIMIT, "trusts": list(TRUSTS)}).mappings().all()
        for row in rows:
            body = source_text(row["title"], row["summary"])
            matched = PREFILTER.search(body) is not None
            if matched and pending >= max_pending:
                continue  # 待ちが減ったら次の回で依頼する
            jid = job_id(row["report_id"], row["content_hash"])
            if matched:
                write_job(in_dir, ExtractInput(jid, row["report_id"], row["content_hash"], row["title"],
                                               row["url"], row["summary"]))
                pending += 1
                result.queued += 1
            else:
                result.skipped += 1
            conn.execute(text("DELETE FROM report_claims WHERE report_id = :r"), {"r": row["report_id"]})
            conn.execute(text("""
                INSERT INTO report_extractions (report_id, content_hash, job_id, status, reason, attempts,
                  queued_at, updated_at)
                VALUES (:r, :h, :j, :s, :reason, 0, :q, :now)
                ON CONFLICT(report_id) DO UPDATE SET content_hash = excluded.content_hash, job_id = excluded.job_id,
                  status = excluded.status, reason = excluded.reason, attempts = 0, provider = NULL, model = NULL,
                  prompt_version = NULL, about_specific_packages = NULL, claims = 0, grounded_claims = 0,
                  error = NULL, queued_at = excluded.queued_at, finished_at = NULL, updated_at = excluded.updated_at
            """), {"r": row["report_id"], "h": row["content_hash"], "j": jid if matched else None,
                   "s": "queued" if matched else "skipped", "reason": None if matched else "prefilter",
                   "q": now if matched else None, "now": now})


def sync_jobs(engine: Engine, in_dir: Path) -> None:
    """in/ を queued の記事と揃える。記事が更新されて古くなった依頼は消し、ファイルが無くなった依頼は書き直す。"""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT e.job_id, r.report_id, r.content_hash, r.title, r.summary, r.url FROM report_extractions e
            JOIN reports r ON r.report_id = e.report_id AND r.content_hash = e.content_hash
            WHERE e.status = 'queued'
        """)).mappings().all()
    queued = {row["job_id"]: row for row in rows}
    for jid in set(list_ids(in_dir)) - set(queued):
        (in_dir / f"{jid}.json").unlink(missing_ok=True)
    for jid, row in queued.items():
        if not (in_dir / f"{jid}.json").exists():
            write_job(in_dir, ExtractInput(jid, row["report_id"], row["content_hash"], row["title"], row["url"],
                                           row["summary"]))


def run(engine: Engine, in_dir: Path, out_dir: Path, now: str) -> ExtractResult:
    result = ingest(engine, in_dir, out_dir, now)
    queue(engine, in_dir, now, result)
    sync_jobs(engine, in_dir)
    return result
