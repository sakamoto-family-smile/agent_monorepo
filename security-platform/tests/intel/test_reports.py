"""L4: フィードの解析と reports への取り込みのテスト (ネットワークなし)。"""
from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import text

from src.common.db import make_engine
from src.common.migrate import upgrade_all
from src.common.paths import DataPaths
from src.common.timeutil import to_iso, utc_now
from src.intel.pipeline import IntelPipeline
from src.intel.sources import feeds as feeds_mod
from src.intel.sources.feeds import FeedConfig, FeedResponse, InvalidFeed, fetch_feed, load_feeds, parse_feed
from src.notify.health import feed_checks


def rss2(*items: tuple[str, str]) -> bytes:
    body = "".join(
        f"<item><title>{t}</title><link>https://ex.test/{g}</link><guid>{g}</guid>"
        f"<pubDate>Thu, 29 Oct 2026 06:43:00 +0900</pubDate>"
        f"<description><![CDATA[<p>Malicious <b>pkg</b> found.</p><script>evil()</script>"
        f"<a href='/advisory/{g}'>advisory</a><a href='javascript:x'>x</a>]]></description></item>"
        for g, t in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>c</title>{body}</channel></rss>'.encode()


RDF = b"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns="http://purl.org/rss/1.0/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel rdf:about="https://www.jpcert.or.jp/"><title>JPCERT</title></channel>
  <item rdf:about="https://www.jpcert.or.jp/at/2026/at260001.html">
    <title>\xe6\xb3\xa8\xe6\x84\x8f\xe5\x96\x9a\xe8\xb5\xb7: PHP</title>
    <link>https://www.jpcert.or.jp/at/2026/at260001.html</link>
    <dc:date>2026-10-29T15:43:00+09:00</dc:date>
  </item>
</rdf:RDF>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Socket</title>
  <entry><id>urn:socket:1</id><title>Malicious Claude Code 2.1.313 extension</title>
    <link rel="alternate" href="https://socket.dev/blog/x"/><updated>2026-10-30T09:26:06.05Z</updated>
    <content type="html">&lt;p&gt;Open VSX &lt;a href="https://open-vsx.org/x"&gt;listing&lt;/a&gt;&lt;/p&gt;</content>
  </entry>
</feed>"""


def test_parse_rss2_rdf_atom():
    [e] = parse_feed(rss2(("a1", "Title &amp; more")))
    assert (e.guid, e.url, e.title) == ("a1", "https://ex.test/a1", "Title & more")
    assert e.summary == "Malicious pkg found.\nadvisoryx" and "evil" not in e.summary
    assert e.links == ["https://ex.test/advisory/a1"]  # 相対リンクは記事の URL で解決し、javascript: は捨てる
    assert e.published_at == "2026-10-28T21:43:00.000000Z"

    [j] = parse_feed(RDF)
    assert j.guid == j.url == "https://www.jpcert.or.jp/at/2026/at260001.html"
    assert j.title == "注意喚起: PHP" and j.published_at == "2026-10-29T06:43:00.000000Z"

    [a] = parse_feed(ATOM)
    assert (a.guid, a.url) == ("urn:socket:1", "https://socket.dev/blog/x")
    assert a.summary == "Open VSX listing" and a.links == ["https://open-vsx.org/x"]


def test_parse_rejects_dtd_and_unknown_formats():
    xxe = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss><channel/></rss>'
    bomb = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><rss>&b;</rss>'
    for body in (xxe, bomb, b"<html><body/></html>", b"not xml"):
        with pytest.raises(InvalidFeed):
            parse_feed(body)


def test_parse_keeps_newest_entries(monkeypatch):
    monkeypatch.setattr(feeds_mod, "MAX_ENTRIES", 2)
    body = rss2(("a", "a"), ("b", "b"), ("c", "c")).replace(b"Thu, 29 Oct 2026", b"Fri, 30 Oct 2026", 1)
    assert [e.guid for e in parse_feed(body)][0] == "a"
    assert len(parse_feed(body)) == 2


def test_load_feeds_validation(tmp_path):
    p = tmp_path / "feeds.yaml"
    p.write_text("feeds:\n  - {id: ok-1, url: 'https://a.test/f', trust: official, lang: ja}\n")
    assert load_feeds(p) == [FeedConfig("ok-1", "https://a.test/f", "official", "ja")]
    for bad in ("{id: x, url: 'http://a.test/f', trust: official}",
                "{id: 'Bad Id', url: 'https://a.test/f', trust: official}",
                "{id: x, url: 'https://a.test/f', trust: rumor}"):
        p.write_text(f"feeds:\n  - {bad}\n")
        with pytest.raises(ValueError):
            load_feeds(p)
    p.write_text("feeds:\n  - {id: x, url: 'https://a.test/1', trust: news}\n  - {id: x, url: 'https://a.test/2', trust: news}\n")
    with pytest.raises(ValueError):
        load_feeds(p)


def test_fetch_feed_conditional_and_size_limit(monkeypatch):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(req.headers)
        if req.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=b"x" * 100, headers={"ETag": '"v1"', "Last-Modified": "Sat"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    r = fetch_feed(client, "https://a.test/f", None, None)
    assert (r.status, r.etag, r.last_modified, len(r.body)) == (200, '"v1"', "Sat", 100)
    r = fetch_feed(client, "https://a.test/f", '"v1"', "Sat")
    assert (r.status, r.body, r.etag) == (304, b"", '"v1"') and seen["if-modified-since"] == "Sat"
    monkeypatch.setattr(feeds_mod, "MAX_FEED_BYTES", 50)
    with pytest.raises(InvalidFeed):
        fetch_feed(client, "https://a.test/f", None, None)


# ── 取り込み ─────────────────────────────────────────────────────────────
A = FeedConfig("feed-a", "https://a.test/feed", "research", "en")
B = FeedConfig("feed-b", "https://b.test/feed", "official", "ja")


class Remote:
    def __init__(self) -> None:
        self.bodies: dict[str, bytes] = {}
        self.errors: dict[str, Exception] = {}
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, url: str, etag: str | None, last_modified: str | None) -> FeedResponse:
        self.calls.append((url, etag))
        if url in self.errors:
            raise self.errors[url]
        body = self.bodies[url]
        tag = f'"{hash(body)}"'
        if etag == tag:
            return FeedResponse(304, b"", etag, last_modified)
        return FeedResponse(200, body, tag, None)


@pytest.fixture
def reports_env(tmp_path):
    paths = DataPaths(tmp_path / "data")
    upgrade_all(paths)
    remote = Remote()

    def make(feeds: list[FeedConfig]) -> IntelPipeline:
        return IntelPipeline(
            make_engine(paths.sqlite_path("intel")), paths, None, lambda _: b"",  # type: ignore[arg-type]
            kev_url="", epss_url="", epss_delta=0.1, incremental_max_per_ecosystem=1, full_snapshots_kept=1,
            feeds=feeds, fetch_feed=remote,
        )

    return make, remote


def rows(p: IntelPipeline, sql: str) -> list[tuple]:
    with p.engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql)).all()]


def test_reports_initial_then_new_and_updated(reports_env):
    make, remote = reports_env
    p = make([A])
    remote.bodies[A.url] = rss2(("a1", "first"), ("a1", "duplicate in the same feed"))
    r = p.run_reports()
    assert (r.new, r.updated) == (1, 0)
    [(title, initial, raw_ref, links)] = rows(p, "SELECT title, initial, raw_ref, links_json FROM reports")
    assert (title, initial) == ("first", 1)  # 初回の取得で既にあった記事
    assert raw_ref.startswith("raw/reports/dt=") and json.loads(links) == ["https://ex.test/advisory/a1"]

    r = p.run_reports()  # 304
    assert (r.new, r.updated, r.unchanged_feeds) == (0, 0, 1)

    remote.bodies[A.url] = rss2(("a2", "second"), ("a1", "first (updated)"))
    r = p.run_reports()
    assert (r.new, r.updated) == (1, 1)
    got = dict(rows(p, "SELECT guid, initial FROM reports"))
    assert got == {"a1": 1, "a2": 0}
    assert rows(p, "SELECT fetched, changed, status FROM source_runs WHERE source = 'reports' "
                   "ORDER BY started_at DESC LIMIT 1") == [(1, 1, "success")]


def test_one_feed_failure_does_not_stop_others(reports_env):
    make, remote = reports_env
    p = make([A, B])
    remote.bodies[A.url] = rss2(("a1", "a"))
    remote.bodies[B.url] = b"<html>not a feed</html>"
    r = p.run_reports()
    assert r.new == 1 and r.failed == ["feed-b"]
    [(ok_at, fail_at, err, n)] = rows(p, "SELECT last_success_at, last_error_at, last_error, consecutive_failures "
                                         "FROM feeds WHERE feed_id = 'feed-b'")
    assert ok_at is None and fail_at and err.startswith("InvalidFeed") and n == 1
    # 壊れていたフィードが直れば、そのフィードの最初の記事は initial になる (古い記事で通知しない)
    remote.bodies[B.url] = rss2(("b1", "b"))
    p.run_reports()
    assert rows(p, "SELECT initial, trust, lang FROM reports WHERE feed_id = 'feed-b'") == [(1, "official", "ja")]
    assert rows(p, "SELECT consecutive_failures FROM feeds WHERE feed_id = 'feed-b'") == [(0,)]


def test_all_feeds_failing_fails_the_job(reports_env):
    make, remote = reports_env
    p = make([A])
    remote.errors[A.url] = httpx.ConnectError("offline")
    with pytest.raises(RuntimeError, match="all 1 feeds failed"):
        p.run_reports()
    assert rows(p, "SELECT status FROM source_runs WHERE source = 'reports'") == [("failed",)]


def test_feed_config_changes(reports_env):
    make, remote = reports_env
    remote.bodies[A.url] = rss2(("a1", "a"))
    make([A]).run_reports()
    moved = FeedConfig("feed-a", "https://a.test/new-feed", "research", "en")
    remote.bodies[moved.url] = rss2(("a1", "a"))
    remote.calls.clear()
    p = make([moved, B])
    remote.bodies[B.url] = rss2(("b1", "b"))
    p.run_reports()
    assert remote.calls[0] == (moved.url, None)  # URL が変わったら ETag を送らない
    p = make([B])
    p.run_reports()
    assert dict(rows(p, "SELECT feed_id, enabled FROM feeds")) == {"feed-a": 0, "feed-b": 1}


def test_feed_health_checks(reports_env):
    make, remote = reports_env
    p = make([A, B])
    remote.bodies[A.url] = rss2(("a1", "a"))
    remote.errors[B.url] = httpx.ConnectError("down")
    p.run_reports()
    now = utc_now()
    assert {c.key: c.ok for c in feed_checks(p.engine, now)} == {"feed:feed-a": True, "feed:feed-b": True}
    p.run_reports()
    p.run_reports()  # 一度も取れないまま 3 回失敗
    checks = {c.key: c for c in feed_checks(p.engine, now)}
    assert not checks["feed:feed-b"].ok and "ConnectError" in checks["feed:feed-b"].detail
    with p.engine.begin() as conn:
        conn.execute(text("UPDATE feeds SET last_success_at = :t WHERE feed_id = 'feed-a'"),
                     {"t": to_iso(now - timedelta(hours=25))})
    assert not {c.key: c.ok for c in feed_checks(p.engine, now)}["feed:feed-a"]
