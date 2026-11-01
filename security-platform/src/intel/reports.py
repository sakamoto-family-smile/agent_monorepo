"""L4: フィードの記事を reports に取り込む (intel の reports ジョブ)。

フィードごとに条件付き GET → 内容が変わっていれば原文を data/raw/reports/ に保存 → 記事を upsert。
1 つのフィードの失敗では止めない (feeds に記録し、notify が feed:<id> として監視する)。
全部のフィードが失敗したときだけジョブを失敗にする (ネットワークが無いなど)。
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import Connection, Engine, text

from ..common.raw_store import RawStore
from .sources.feeds import FeedConfig, FeedEntry, FeedResponse, parse_feed

logger = logging.getLogger(__name__)

RAW_SOURCE = "reports"
FetchFeed = Callable[[str, str | None, str | None], FeedResponse]


@dataclass
class ReportsResult:
    new: int = 0
    updated: int = 0
    unchanged_feeds: int = 0
    failed: list[str] = field(default_factory=list)


def report_id(feed_id: str, guid: str) -> str:
    return "rep_" + hashlib.sha256(f"{feed_id}\n{guid}".encode()).hexdigest()[:24]


def _content_hash(e: FeedEntry) -> str:
    body = json.dumps([e.title, e.url, e.summary, e.published_at, e.links], ensure_ascii=False)
    return hashlib.sha256(body.encode()).hexdigest()


def _sync_feeds(conn: Connection, feeds: list[FeedConfig], now: str) -> None:
    """設定のフィードを登録し、設定から消えたものは監視をやめる。URL が変わったら条件付き GET をやり直す。"""
    for f in feeds:
        conn.execute(text("""
            INSERT INTO feeds (feed_id, url, trust, lang, enabled, updated_at)
            VALUES (:id, :url, :trust, :lang, 1, :now)
            ON CONFLICT(feed_id) DO UPDATE SET
              etag = CASE WHEN feeds.url = excluded.url THEN feeds.etag END,
              last_modified = CASE WHEN feeds.url = excluded.url THEN feeds.last_modified END,
              content_sha256 = CASE WHEN feeds.url = excluded.url THEN feeds.content_sha256 END,
              url = excluded.url, trust = excluded.trust, lang = excluded.lang, enabled = 1,
              updated_at = excluded.updated_at
        """), {"id": f.id, "url": f.url, "trust": f.trust, "lang": f.lang, "now": now})
    ids = [f.id for f in feeds]
    marks = ", ".join(f":f{i}" for i in range(len(ids))) or "''"
    conn.execute(text(f"UPDATE feeds SET enabled = 0, updated_at = :now WHERE feed_id NOT IN ({marks})"),  # nosec B608
                 {"now": now, **{f"f{i}": v for i, v in enumerate(ids)}})


def _upsert(conn: Connection, f: FeedConfig, entries: list[FeedEntry], raw_ref: str, initial: bool,
            now: str, result: ReportsResult) -> None:
    seen: set[str] = set()
    for e in entries:  # 同じ guid が 1 つのフィードに 2 回載っていることがある。新しい方 (先) を使う
        if e.guid in seen:
            continue
        seen.add(e.guid)
        rid = report_id(f.id, e.guid)
        h = _content_hash(e)
        old = conn.execute(text("SELECT content_hash FROM reports WHERE report_id = :r"), {"r": rid}).scalar()
        if old == h:
            continue
        params = {"r": rid, "feed": f.id, "guid": e.guid, "url": e.url, "title": e.title, "summary": e.summary,
                  "links": json.dumps(e.links, ensure_ascii=False), "trust": f.trust, "lang": f.lang,
                  "pub": e.published_at, "initial": initial, "h": h, "raw": raw_ref, "now": now}
        if old is None:
            conn.execute(text("""
                INSERT INTO reports (report_id, feed_id, guid, url, title, summary, links_json, trust, lang,
                  published_at, initial, content_hash, raw_ref, first_seen_at, updated_at)
                VALUES (:r, :feed, :guid, :url, :title, :summary, :links, :trust, :lang, :pub, :initial, :h, :raw,
                  :now, :now)
            """), params)
            result.new += 1
        else:
            conn.execute(text("""
                UPDATE reports SET url = :url, title = :title, summary = :summary, links_json = :links,
                  trust = :trust, lang = :lang, published_at = :pub, content_hash = :h, raw_ref = :raw,
                  updated_at = :now
                WHERE report_id = :r
            """), params)
            result.updated += 1


def _collect_one(engine: Engine, raw: RawStore, f: FeedConfig, fetch: FetchFeed, run_id: str, now: str,
                 result: ReportsResult) -> None:
    with engine.connect() as conn:
        state = conn.execute(text(
            "SELECT etag, last_modified, content_sha256, last_success_at FROM feeds WHERE feed_id = :f"
        ), {"f": f.id}).one()
    resp = fetch(f.url, state.etag, state.last_modified)
    sha = hashlib.sha256(resp.body).hexdigest() if resp.status == 200 else state.content_sha256
    with engine.begin() as conn:
        if resp.status == 304 or sha == state.content_sha256:
            result.unchanged_feeds += 1
        else:
            raw_ref = raw.relative(raw.write_bytes(RAW_SOURCE, f"{f.id}-{run_id}.xml", resp.body))
            entries = parse_feed(resp.body)
            _upsert(conn, f, entries, raw_ref, state.last_success_at is None, now, result)
        conn.execute(text("""
            UPDATE feeds SET etag = :etag, last_modified = :lm, content_sha256 = :sha, last_success_at = :now,
              consecutive_failures = 0, updated_at = :now
            WHERE feed_id = :f
        """), {"etag": resp.etag, "lm": resp.last_modified, "sha": sha, "now": now, "f": f.id})


def collect(engine: Engine, raw: RawStore, feeds: list[FeedConfig], fetch: FetchFeed, run_id: str,
            now: str) -> ReportsResult:
    result = ReportsResult()
    with engine.begin() as conn:
        _sync_feeds(conn, feeds, now)
    for f in feeds:
        try:
            _collect_one(engine, raw, f, fetch, run_id, now, result)
        except Exception as e:  # 1 つのフィードの失敗で他を止めない
            logger.warning("feed %s failed: %s: %s", f.id, type(e).__name__, e)
            result.failed.append(f.id)
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE feeds SET last_error = :e, last_error_at = :now,
                      consecutive_failures = consecutive_failures + 1, updated_at = :now
                    WHERE feed_id = :f
                """), {"e": f"{type(e).__name__}: {e}"[:1000], "now": now, "f": f.id})
    if feeds and len(result.failed) == len(feeds):
        raise RuntimeError(f"all {len(feeds)} feeds failed")
    return result
