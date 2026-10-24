"""A1 のジョブ。各ジョブは source_runs に実行記録を残す (FR-I07 の監視元)。

intel.db に書くのはこのプロセスだけにする (docker compose の intel サービス)。
"""
from __future__ import annotations

import gzip
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, bindparam, text

from ..common.events import Outbox
from ..common.paths import DataPaths
from ..common.raw_store import RawStore
from ..common.timeutil import parse_iso, to_iso, utc_now_iso
from . import changes
from .changes import RunContext
from .osv_record import OsvRecord, parse_record
from .records import existing_hashes, upsert_osv_record
from .signals import upsert_epss, upsert_kev
from .sources import epss as epss_source
from .sources import kev as kev_source
from .sources.osv import (
    ModifiedEntry,
    OsvClient,
    ecosystem_slug,
    iter_zip_records,
    publish_scanner_db,
)

logger = logging.getLogger(__name__)

BATCH = 1000
FETCH_WORKERS = 8
OSV_CURSOR = "osv"
META_BOOTSTRAPPED = "bootstrap_completed_at"
META_BOOTSTRAP_DONE_ECOS = "bootstrap_osv_done"
META_BOOTSTRAP_HEAD = "bootstrap_osv_head"  # 再開しても差分カーソルの起点を最初の開始時点に固定する
# 差分取得はカーソルより少し前から読む (エクスポートの遅延で古い時刻の行が後から現れても拾う)。
# 既に同じ modified で取り込み済みのレコードは取得しないので、重なりのコストは小さい
OSV_OVERLAP = timedelta(hours=2)


class IntelPipeline:
    def __init__(
        self,
        engine: Engine,
        paths: DataPaths,
        osv: OsvClient,
        fetch_bytes: Callable[[str], bytes],
        *,
        kev_url: str,
        epss_url: str,
        epss_delta: float,
        incremental_max_per_ecosystem: int,
        full_snapshots_kept: int,
        ecosystems: list[str] | None = None,
    ) -> None:
        self.engine = engine
        self.paths = paths
        self.raw = RawStore(paths.raw_dir)
        self.osv = osv
        self.fetch_bytes = fetch_bytes
        self.kev_url = kev_url
        self.epss_url = epss_url
        self.epss_delta = epss_delta
        self.max_per_eco = incremental_max_per_ecosystem
        self.keep_full = full_snapshots_kept
        self.ecosystems = ecosystems

    # ── 実行記録 ──────────────────────────────────────────────────────────
    @contextmanager
    def _run(self, source: str, mode: str, *, emit: bool) -> Iterator[RunContext]:
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO source_runs (run_id, source, mode, started_at, status) "
                     "VALUES (:r, :s, :m, :t, 'running')"),
                {"r": run_id, "s": source, "m": mode, "t": utc_now_iso()},
            )
        ctx = RunContext(run_id, Outbox(self.paths.events_dir, "intel"), emit_events=emit)
        try:
            yield ctx
        except Exception as e:
            ctx.outbox.discard()
            self._finish(ctx, "failed", f"{type(e).__name__}: {e}"[:2000], 0)
            raise
        self._finish(ctx, "success", None, ctx.fetched)

    def _finish(self, ctx: RunContext, status: str, error: str | None, fetched: int) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE source_runs SET finished_at = :t, status = :s, fetched = :f, "
                     "changed = :c, skipped = :k, error = :e WHERE run_id = :r"),
                {"t": utc_now_iso(), "s": status, "f": fetched, "c": ctx.changed,
                 "k": ctx.skipped, "e": error, "r": ctx.run_id},
            )

    def last_success(self, source: str) -> datetime | None:
        with self.engine.connect() as conn:
            v = conn.execute(
                text("SELECT MAX(finished_at) FROM source_runs WHERE source = :s AND status = 'success'"),
                {"s": source},
            ).scalar()
        return parse_iso(v) if v else None

    def _drain_dirty(self, ctx: RunContext) -> None:
        """advisories_dirty を空になるまで再集計する。前回の途中終了分もここで回収される。"""
        while True:
            with self.engine.begin() as conn:
                ids = conn.execute(
                    text("SELECT advisory_id FROM advisories_dirty ORDER BY advisory_id LIMIT :n"),
                    {"n": BATCH},
                ).scalars().all()
                for advisory_id in ids:
                    changes.apply(conn, ctx, advisory_id)
                    conn.execute(
                        text("DELETE FROM advisories_dirty WHERE advisory_id = :a"), {"a": advisory_id}
                    )
            ctx.outbox.flush()
            if len(ids) < BATCH:
                return

    # ── meta / cursor ─────────────────────────────────────────────────────
    def _get(self, table: str, key_col: str, val_col: str, key: str) -> str | None:
        with self.engine.connect() as conn:
            return conn.execute(
                text(f"SELECT {val_col} FROM {table} WHERE {key_col} = :k"), {"k": key}
            ).scalar()

    def _set_meta(self, key: str, value: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO meta (key, value) VALUES (:k, :v) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value"),
                {"k": key, "v": value},
            )

    def osv_cursor(self) -> str | None:
        return self._get("source_cursors", "source", "cursor", OSV_CURSOR)

    def _advance_osv_cursor(self, value: str | None) -> None:
        current = self.osv_cursor()
        if value is None or (current and parse_iso(current) >= parse_iso(value)):
            return
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO source_cursors (source, cursor, updated_at) VALUES (:s, :c, :u) "
                     "ON CONFLICT(source) DO UPDATE SET cursor = excluded.cursor, "
                     "updated_at = excluded.updated_at"),
                {"s": OSV_CURSOR, "c": value, "u": utc_now_iso()},
            )

    def is_bootstrapped(self) -> bool:
        return self._get("meta", "key", "value", META_BOOTSTRAPPED) is not None

    # ── KEV / EPSS ────────────────────────────────────────────────────────
    def run_kev(self, *, emit: bool = True) -> None:
        with self._run("kev", "snapshot", emit=emit) as ctx:
            body = self.fetch_bytes(self.kev_url)
            raw = self.raw.write_bytes("kev", f"kev-{ctx.run_id}.json", body)
            entries = kev_source.parse_kev(body)
            ctx.fetched = len(entries)
            with self.engine.begin() as conn:
                touched = upsert_kev(conn, ctx, entries, self.raw.relative(raw))
                for advisory_id in sorted(touched):
                    changes.apply(conn, ctx, advisory_id)
            ctx.outbox.flush()

    def run_epss(self, *, emit: bool = True) -> None:
        with self._run("epss", "snapshot", emit=emit) as ctx:
            body = self.fetch_bytes(self.epss_url)
            self.raw.write_bytes("epss", f"epss-{ctx.run_id}.csv.gz", body)
            with self.engine.begin() as conn:
                ctx.fetched = upsert_epss(
                    conn, ctx, epss_source.iter_epss(body), epss_source.score_date(body),
                    self.epss_delta,
                )
                changes.apply_signals(conn, ctx)
            ctx.outbox.flush()

    # ── OSV 全量 ──────────────────────────────────────────────────────────
    def _ingest_records(
        self, ctx: RunContext, records: Iterable[tuple[str, dict[str, Any]]]
    ) -> int:
        count = 0
        batch: dict[str, tuple[str, OsvRecord]] = {}

        def flush() -> None:
            with self.engine.begin() as conn:
                old = existing_hashes(conn, list(batch))
                for record_id, (ref, rec) in batch.items():
                    upsert_osv_record(conn, rec, ref, old.get(record_id))
            batch.clear()

        for ref, raw in records:
            try:
                rec = parse_record(raw)
            except Exception:  # 1 件の不正なレコードで取り込み全体を止めない
                logger.warning("skip malformed OSV record at %s", ref, exc_info=True)
                ctx.skipped += 1
                continue
            batch[rec.record_id] = (ref, rec)
            count += 1
            if len(batch) >= BATCH:
                flush()
        if batch:
            flush()
        self._drain_dirty(ctx)
        return count

    def _ingest_zip(self, ctx: RunContext, ecosystem: str) -> int:
        zip_path = self.osv.download_all_zip(
            ecosystem, self.raw, f"full-{ctx.run_id}/{ecosystem_slug(ecosystem)}.zip"
        )
        rel = self.raw.relative(zip_path)
        n = self._ingest_records(
            ctx, ((f"{rel}#{member}", rec) for member, rec in iter_zip_records(zip_path))
        )
        publish_scanner_db(zip_path, self.paths.osv_db_dir, ecosystem)
        logger.info("osv %s: %d records", ecosystem, n)
        return n

    def run_osv_full(self, *, emit: bool = True, bootstrap: bool = False) -> None:
        with self._run("osv_full", "bootstrap" if bootstrap else "full", emit=emit) as ctx:
            self._drain_dirty(ctx)
            head = self.osv.latest_modified()
            if bootstrap:
                pinned = self._get("meta", "key", "value", META_BOOTSTRAP_HEAD)
                if pinned is None and head is not None:
                    self._set_meta(META_BOOTSTRAP_HEAD, head)
                head = pinned or head
            done = set(json.loads(self._get("meta", "key", "value", META_BOOTSTRAP_DONE_ECOS) or "[]"))
            total = 0
            for eco in self.ecosystems or self.osv.list_ecosystems():
                if bootstrap and eco in done:
                    continue
                total += self._ingest_zip(ctx, eco)
                if bootstrap:
                    done.add(eco)
                    self._set_meta(META_BOOTSTRAP_DONE_ECOS, json.dumps(sorted(done)))
            ctx.fetched = total
            self._advance_osv_cursor(head)
            self.raw.prune_dirs("osv", "full-", self.keep_full)

    # ── OSV 差分 ──────────────────────────────────────────────────────────
    def _fetch_changed(self, entries: list[ModifiedEntry]) -> list[dict[str, Any]]:
        unique: dict[str, ModifiedEntry] = {}
        for e in entries:
            unique.setdefault(e.record_id, e)
        with ThreadPoolExecutor(FETCH_WORKERS) as pool:
            fetched = pool.map(lambda e: self.osv.fetch_record(e.ecosystem, e.record_id), unique.values())
            return [r for r in fetched if r is not None]

    def _not_yet_ingested(self, entries: list[ModifiedEntry]) -> list[ModifiedEntry]:
        """同じ (かそれより新しい) modified で取り込み済みのものを除く。"""
        ids = sorted({e.record_id for e in entries})
        known: dict[str, str] = {}
        with self.engine.connect() as conn:
            for i in range(0, len(ids), 500):
                rows = conn.execute(
                    text("SELECT record_id, modified_at FROM osv_records WHERE record_id IN :ids")
                    .bindparams(bindparam("ids", expanding=True)),
                    {"ids": ids[i : i + 500]},
                ).all()
                known.update({r[0]: r[1] for r in rows if r[1]})
        return [
            e for e in entries
            if e.record_id not in known or parse_iso(known[e.record_id]) < parse_iso(e.modified)
        ]

    def _save_incremental_raw(self, run_id: str, records: list[dict[str, Any]]) -> Path:
        body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
        return self.raw.write_bytes("osv", f"incr-{run_id}.jsonl.gz", gzip.compress(body.encode()))

    def run_osv_incremental(self, *, emit: bool = True) -> None:
        cursor = self.osv_cursor()
        if cursor is None:
            raise RuntimeError("osv cursor is not set; run bootstrap first")
        with self._run("osv", "incremental", emit=emit) as ctx:
            self._drain_dirty(ctx)
            entries = self.osv.modified_since(to_iso(parse_iso(cursor) - OSV_OVERLAP))
            pending = self._not_yet_ingested(entries)
            by_eco: dict[str, list[ModifiedEntry]] = defaultdict(list)
            for e in pending:
                by_eco[e.ecosystem].append(e)
            bulk = sorted(eco for eco, es in by_eco.items() if len(es) > self.max_per_eco)
            single = [e for eco, es in by_eco.items() if eco not in bulk for e in es]
            total = sum(self._ingest_zip(ctx, eco) for eco in bulk)
            records = self._fetch_changed(single)
            if records:
                rel = self.raw.relative(self._save_incremental_raw(ctx.run_id, records))
                total += self._ingest_records(ctx, ((f"{rel}#{r['id']}", r) for r in records))
            ctx.fetched = total
            self._advance_osv_cursor(entries[0].modified if entries else None)

    # ── ブートストラップ ──────────────────────────────────────────────────
    def bootstrap(self) -> bool:
        """未完了なら全量取り込みを行う (イベント抑止)。実行したら True。中断しても再開できる。"""
        if self.is_bootstrapped():
            return False
        self.run_osv_full(emit=False, bootstrap=True)
        self.run_kev(emit=False)
        self.run_epss(emit=False)
        outbox = Outbox(self.paths.events_dir, "intel")
        now = utc_now_iso()
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO meta (key, value) VALUES (:k, :v)"), {"k": META_BOOTSTRAPPED, "v": now}
            )
            outbox.publish(conn, changes.EVENT_BOOTSTRAP_COMPLETED, {"completed_at": now})
        outbox.flush()
        return True
