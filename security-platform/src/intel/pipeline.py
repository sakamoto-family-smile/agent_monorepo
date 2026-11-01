"""A1 のジョブ。各ジョブは source_runs に実行記録を残す (FR-I07 の監視元)。

intel.db に書くのはこのプロセスだけにする (docker compose の intel サービス)。
"""
from __future__ import annotations

import gzip
import hashlib
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
from . import changes, reports
from .changes import RunContext
from .osv_record import OsvRecord, parse_record
from .records import existing_hashes, upsert_osv_record
from .reports import FetchFeed
from .signals import upsert_epss, upsert_kev
from .sources import epss as epss_source
from .sources import kev as kev_source
from .sources.feeds import FeedConfig
from .sources.osv import (
    MalformedRecord,
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
META_KEV_SHA = "kev_sha256"
META_KEV_RAW = "kev_raw_ref"
META_EPSS_SCORE_DATE = "epss_score_date"
META_EPSS_MODEL = "epss_model_version"
# 本文が 404 だったレコードを取り直す回数 (毎時の差分取得ごとに 1 回。超えたら記録だけ残す)
MISSING_MAX_ATTEMPTS = 24
FULL_PREFIX = "full-"  # 週次の全量取得 (世代数で保持)
BULK_PREFIX = "bulk-"  # 差分が多いときのエコシステム単位の全量取得 (日数で保持)
INCR_PREFIX = "incr-"


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
        raw_retention: timedelta = timedelta(days=30),
        min_free_bytes: int = 0,
        feeds: list[FeedConfig] | None = None,
        fetch_feed: FetchFeed | None = None,
    ) -> None:
        self.engine = engine
        self.paths = paths
        self.raw = RawStore(paths.raw_dir, min_free_bytes=min_free_bytes)
        self.osv = osv
        self.fetch_bytes = fetch_bytes
        self.kev_url = kev_url
        self.epss_url = epss_url
        self.epss_delta = epss_delta
        self.max_per_eco = incremental_max_per_ecosystem
        self.keep_full = full_snapshots_kept
        self.ecosystems = ecosystems
        self.raw_retention = raw_retention
        self.feeds = feeds or []
        self.fetch_feed = fetch_feed

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
        """advisories_dirty を空になるまで再集計する。前回の途中終了分もここで回収される。

        再集計の途中で下流の Advisory が積まれることがある (深刻度の引き継ぎ) ので、空の読み出しで終える。
        """
        while True:
            with self.engine.begin() as conn:
                ids = conn.execute(
                    text("SELECT advisory_id FROM advisories_dirty ORDER BY advisory_id LIMIT :n"),
                    {"n": BATCH},
                ).scalars().all()
                if not ids:
                    return
                for advisory_id in ids:
                    changes.apply(conn, ctx, advisory_id)
                    conn.execute(
                        text("DELETE FROM advisories_dirty WHERE advisory_id = :a"), {"a": advisory_id}
                    )
            ctx.outbox.flush()

    # ── meta / cursor ─────────────────────────────────────────────────────
    def _scalar(self, sql: str, key: str) -> str | None:
        with self.engine.connect() as conn:
            return conn.execute(text(sql), {"k": key}).scalar()

    def _meta(self, key: str) -> str | None:
        return self._scalar("SELECT value FROM meta WHERE key = :k", key)

    def _set_meta(self, key: str, value: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO meta (key, value) VALUES (:k, :v) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value"),
                {"k": key, "v": value},
            )

    def osv_cursor(self) -> str | None:
        return self._scalar("SELECT cursor FROM source_cursors WHERE source = :k", OSV_CURSOR)

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
        return self._meta(META_BOOTSTRAPPED) is not None

    def _successful_runs(self, source: str) -> set[str]:
        with self.engine.connect() as conn:
            return set(conn.execute(
                text("SELECT run_id FROM source_runs WHERE source = :s AND status = 'success'"),
                {"s": source},
            ).scalars())

    # ── KEV / EPSS ────────────────────────────────────────────────────────
    def run_kev(self, *, emit: bool = True) -> None:
        """毎時取得するが、内容が前回と同じなら生データは保存しない (年 10GB 超になるため)。"""
        with self._run("kev", "snapshot", emit=emit) as ctx:
            body = self.fetch_bytes(self.kev_url)
            entries = kev_source.parse_kev(body)
            ctx.fetched = len(entries)
            sha = hashlib.sha256(body).hexdigest()
            raw_ref = self._meta(META_KEV_RAW)
            if sha != self._meta(META_KEV_SHA) or raw_ref is None:
                raw_ref = self.raw.relative(self.raw.write_bytes("kev", f"kev-{ctx.run_id}.json", body))
            with self.engine.begin() as conn:
                touched = upsert_kev(conn, ctx, entries, raw_ref)
                for advisory_id in sorted(touched):
                    changes.apply(conn, ctx, advisory_id)
                for key, value in ((META_KEV_SHA, sha), (META_KEV_RAW, raw_ref)):
                    conn.execute(
                        text("INSERT INTO meta (key, value) VALUES (:k, :v) "
                             "ON CONFLICT(key) DO UPDATE SET value = excluded.value"),
                        {"k": key, "v": value},
                    )
            ctx.outbox.flush()
            self.raw.prune_older_than("kev", self.raw_retention)

    def run_epss(self, *, emit: bool = True) -> None:
        """同じ score_date のファイルは取り込み直さない。モデルが変わった日は上昇を検知しない。"""
        with self._run("epss", "snapshot", emit=emit) as ctx:
            body = self.fetch_bytes(self.epss_url)
            sd = epss_source.score_date(body)
            if sd is not None and sd == self._meta(META_EPSS_SCORE_DATE):
                logger.info("epss %s already ingested; skipping", sd)
                return
            model = epss_source.model_version(body)
            prev_model = self._meta(META_EPSS_MODEL)
            model_changed = prev_model is not None and model is not None and model != prev_model
            if model_changed:
                logger.warning("EPSS model changed %s -> %s; skipping rise detection", prev_model, model)
            self.raw.write_bytes("epss", f"epss-{ctx.run_id}.csv.gz", body)
            with self.engine.begin() as conn:
                ctx.fetched = upsert_epss(
                    conn, ctx, epss_source.iter_epss(body), sd, self.epss_delta,
                    detect_rises=not model_changed,
                )
                changes.apply_signals(conn, ctx)
                for key, value in ((META_EPSS_SCORE_DATE, sd), (META_EPSS_MODEL, model)):
                    if value is not None:
                        conn.execute(
                            text("INSERT INTO meta (key, value) VALUES (:k, :v) "
                                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value"),
                            {"k": key, "v": value},
                        )
            ctx.outbox.flush()
            self.raw.prune_older_than("epss", self.raw_retention)

    # ── L4: フィードの記事 ────────────────────────────────────────────────
    def run_reports(self, *, emit: bool = True) -> reports.ReportsResult:
        """config/feeds.yaml のフィードを取得して reports に取り込む。fetched は新しい記事の数。"""
        if self.fetch_feed is None:
            raise RuntimeError("fetch_feed is not configured")
        with self._run("reports", "incremental", emit=emit) as ctx:
            r = reports.collect(self.engine, self.raw, self.feeds, self.fetch_feed, ctx.run_id, utc_now_iso())
            ctx.fetched, ctx.changed, ctx.skipped = r.new, r.updated, len(r.failed)
            logger.info("reports: %d new, %d updated, %d unchanged feeds, failed: %s",
                        r.new, r.updated, r.unchanged_feeds, ", ".join(r.failed) or "-")
            self.raw.prune_older_than(reports.RAW_SOURCE, self.raw_retention)
        return r

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
                conn.execute(
                    text("DELETE FROM osv_missing WHERE record_id IN :ids")
                    .bindparams(bindparam("ids", expanding=True)),
                    {"ids": list(batch)},
                )
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

    def _ingest_zip(self, ctx: RunContext, ecosystem: str, prefix: str = FULL_PREFIX) -> int:
        self.raw.ensure_free_space()
        zip_path = self.osv.download_all_zip(
            ecosystem, self.raw, f"{prefix}{ctx.run_id}/{ecosystem_slug(ecosystem)}.zip"
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
                pinned = self._meta(META_BOOTSTRAP_HEAD)
                if pinned is None and head is not None:
                    self._set_meta(META_BOOTSTRAP_HEAD, head)
                head = pinned or head
            done = set(json.loads(self._meta(META_BOOTSTRAP_DONE_ECOS) or "[]"))
            total = 0
            try:
                for eco in self.ecosystems or self.osv.list_ecosystems():
                    if bootstrap and eco in done:
                        continue
                    total += self._ingest_zip(ctx, eco)
                    if bootstrap:
                        done.add(eco)
                        self._set_meta(META_BOOTSTRAP_DONE_ECOS, json.dumps(sorted(done)))
            except Exception:
                if not bootstrap:  # 再開しないので、途中までの数 GB はすぐ消す
                    self.raw.prune_dirs("osv", f"{FULL_PREFIX}{ctx.run_id}", keep=0)
                raise
            ctx.fetched = total
            self._advance_osv_cursor(head)
            # 失敗した実行の途中までのファイルは世代に数えずに消す。ブートストラップは
            # 失敗した実行のファイルも取り込み済み (raw_ref が指す) なので、完了までは残す
            complete = {f"{FULL_PREFIX}{r}" for r in self._successful_runs("osv_full")}
            complete.add(f"{FULL_PREFIX}{ctx.run_id}")
            if not bootstrap:
                self.raw.prune_dirs("osv", FULL_PREFIX, self.keep_full, complete=complete)

    # ── OSV 差分 ──────────────────────────────────────────────────────────
    def _fetch_changed(
        self, ctx: RunContext, entries: list[ModifiedEntry]
    ) -> tuple[list[dict[str, Any]], list[ModifiedEntry]]:
        """(取れたレコード, 404 だったエントリ)。壊れたレコードは飛ばして skipped に数える。"""
        unique: dict[str, ModifiedEntry] = {}
        for e in entries:
            unique.setdefault(e.record_id, e)

        def get(e: ModifiedEntry) -> dict[str, Any] | None | MalformedRecord:
            try:
                return self.osv.fetch_record(e.ecosystem, e.record_id)
            except MalformedRecord as err:
                return err

        records: list[dict[str, Any]] = []
        missing: list[ModifiedEntry] = []
        with ThreadPoolExecutor(FETCH_WORKERS) as pool:
            for e, r in zip(unique.values(), pool.map(get, unique.values()), strict=True):
                if isinstance(r, MalformedRecord):
                    logger.warning("skip malformed OSV record: %s", r)
                    ctx.skipped += 1
                elif r is None:
                    missing.append(e)
                else:
                    records.append(r)
        return records, missing

    def _record_missing(self, missing: list[ModifiedEntry]) -> None:
        if not missing:
            return
        logger.warning("%d OSV records listed in modified_id.csv returned 404: %s",
                       len(missing), ", ".join(e.record_id for e in missing[:20]))
        now = utc_now_iso()
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO osv_missing (record_id, ecosystem, modified, first_missing_at, "
                     "last_checked_at, attempts) VALUES (:id, :eco, :mod, :now, :now, 1) "
                     "ON CONFLICT(record_id) DO UPDATE SET last_checked_at = excluded.last_checked_at, "
                     "attempts = osv_missing.attempts + 1"),
                [{"id": e.record_id, "eco": e.ecosystem, "mod": e.modified, "now": now} for e in missing],
            )

    def _missing_to_retry(self) -> list[ModifiedEntry]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT modified, ecosystem, record_id FROM osv_missing WHERE attempts < :n "
                     "ORDER BY first_missing_at LIMIT 1000"),
                {"n": MISSING_MAX_ATTEMPTS},
            ).all()
        return [ModifiedEntry(*r) for r in rows]

    def missing_count(self) -> int:
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT COUNT(*) FROM osv_missing")).scalar_one()

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
        return self.raw.write_bytes("osv", f"{INCR_PREFIX}{run_id}.jsonl.gz", gzip.compress(body.encode()))

    def run_osv_incremental(self, *, emit: bool = True) -> None:
        cursor = self.osv_cursor()
        if cursor is None:
            raise RuntimeError("osv cursor is not set; run bootstrap first")
        with self._run("osv", "incremental", emit=emit) as ctx:
            self._drain_dirty(ctx)
            entries = self.osv.modified_since(to_iso(parse_iso(cursor) - OSV_OVERLAP))
            wanted = set(self.ecosystems) if self.ecosystems else None
            listed = [e for e in entries if wanted is None or e.ecosystem in wanted]
            pending = self._not_yet_ingested(listed)
            pending_ids = {e.record_id for e in pending}
            pending += [e for e in self._missing_to_retry()
                        if e.record_id not in pending_ids and (wanted is None or e.ecosystem in wanted)]
            by_eco: dict[str, list[ModifiedEntry]] = defaultdict(list)
            for e in pending:
                by_eco[e.ecosystem].append(e)
            bulk = sorted(eco for eco, es in by_eco.items() if len(es) > self.max_per_eco)
            single = [e for eco, es in by_eco.items() if eco not in bulk for e in es]
            total = sum(self._ingest_zip(ctx, eco, BULK_PREFIX) for eco in bulk)
            records, missing = self._fetch_changed(ctx, single)
            if records:
                rel = self.raw.relative(self._save_incremental_raw(ctx.run_id, records))
                total += self._ingest_records(ctx, ((f"{rel}#{r['id']}", r) for r in records))
            self._record_missing(missing)
            ctx.fetched = total
            # カーソルは絞り込み前の先頭で進める (対象外のエコシステムしか動いていなくても前に進む)
            self._advance_osv_cursor(entries[0].modified if entries else None)
            self.raw.prune_older_than("osv", self.raw_retention, prefixes=(INCR_PREFIX, BULK_PREFIX))

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
