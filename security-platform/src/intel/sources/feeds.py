"""L4: 注意喚起・公式の告知・調査会社のフィード (RSS 2.0 / RSS 1.0 (RDF) / Atom)。

フィードは外部の信頼できない入力なので、XML は defusedxml で読む (外部実体・DTD を拒否)。
大きさは MAX_FEED_BYTES で打ち切る。本文の HTML はタグを落としたテキストと、リンク先の一覧にする
(リンクは一次情報の確認に使う。L4 PR3)。
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit
from xml.etree.ElementTree import Element  # 型注釈のみ (解析は defusedxml)  # nosec B405

import httpx
import yaml
from defusedxml import ElementTree as SafeET

from ...common.http import with_retry
from ...common.timeutil import to_iso

Trust = Literal["official", "research", "news"]
TRUSTS: tuple[str, ...] = ("official", "research", "news")
FEED_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MAX_FEED_BYTES = 5_000_000
MAX_ENTRIES = 200  # 1 フィードで取り込む件数 (新しい順)。フィードは普通 10〜50 件
MAX_TITLE = 500
MAX_SUMMARY = 20_000  # 本文 (テキスト化後) の上限。全文を載せるフィードもあるため
MAX_LINKS = 50

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "rss1": "http://purl.org/rss/1.0/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


class InvalidFeed(ValueError):
    pass


@dataclass(frozen=True)
class FeedConfig:
    id: str
    url: str
    trust: Trust
    lang: str = "en"


@dataclass(frozen=True)
class FeedEntry:
    guid: str
    url: str | None
    title: str
    summary: str
    published_at: str | None
    links: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FeedResponse:
    status: int  # 200 / 304
    body: bytes
    etag: str | None
    last_modified: str | None


def load_feeds(path: Path) -> list[FeedConfig]:
    data = yaml.safe_load(path.read_text()) or {}
    feeds: list[FeedConfig] = []
    seen: set[str] = set()
    for i, raw in enumerate(data.get("feeds") or []):
        fid, url, trust = str(raw.get("id", "")), str(raw.get("url", "")), str(raw.get("trust", ""))
        if not FEED_ID.match(fid) or fid in seen:
            raise ValueError(f"{path}: feeds[{i}] の id が不正か重複しています: {fid!r}")
        if urlsplit(url).scheme != "https":
            raise ValueError(f"{path}: {fid} の url は https にしてください")
        if trust not in TRUSTS:
            raise ValueError(f"{path}: {fid} の trust は {'/'.join(TRUSTS)} のどれかです")
        seen.add(fid)
        feeds.append(FeedConfig(fid, url, trust, str(raw.get("lang") or "en")))  # type: ignore[arg-type]
    return feeds


# ── 取得 ──────────────────────────────────────────────────────────────────
def fetch_feed(
    client: httpx.Client, url: str, etag: str | None, last_modified: str | None,
) -> FeedResponse:
    """条件付き GET。304 なら本文は空。MAX_FEED_BYTES を超えたら InvalidFeed。"""
    headers = {"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.1"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    def go() -> FeedResponse:
        with client.stream("GET", url, headers=headers) as r:
            if r.status_code == 304:
                return FeedResponse(304, b"", etag, last_modified)
            r.raise_for_status()
            chunks, size = [], 0
            for chunk in r.iter_bytes():
                size += len(chunk)
                if size > MAX_FEED_BYTES:
                    raise InvalidFeed(f"feed larger than {MAX_FEED_BYTES} bytes")
                chunks.append(chunk)
            return FeedResponse(200, b"".join(chunks), r.headers.get("ETag"), r.headers.get("Last-Modified"))

    return with_retry(go, what=url)


# ── 解析 ──────────────────────────────────────────────────────────────────
class _TextAndLinks(HTMLParser):
    SKIP = {"script", "style", "noscript", "iframe", "svg"}
    BREAK = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote"}

    def __init__(self, base: str | None) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.parts: list[str] = []
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BREAK:
            self.parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                url = urljoin(self.base or "", href.strip())
                if urlsplit(url).scheme in ("http", "https") and url not in self.links:
                    self.links.append(url)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BREAK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str, base: str | None = None) -> tuple[str, list[str]]:
    """(テキスト, リンク先)。改行は段落の区切りだけ残す。"""
    p = _TextAndLinks(base)
    p.feed(html)
    p.close()
    lines = (re.sub(r"[ \t\r\f\v ]+", " ", line).strip() for line in "".join(p.parts).split("\n"))
    text = "\n".join(line for line in lines if line)
    return text, p.links[:MAX_LINKS]


def _text(el: Element | None) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def _date(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return to_iso(dt.astimezone(UTC))


def _clean_url(value: str | None, base: str | None = None) -> str | None:
    if not value:
        return None
    url = urljoin(base or "", value.strip())
    return url if urlsplit(url).scheme in ("http", "https") else None


def _entry(guid: str, url: str | None, title: str, body_html: str, date: str) -> FeedEntry | None:
    guid = (guid or url or "").strip()
    if not guid:
        return None
    summary, links = html_to_text(body_html, url)
    return FeedEntry(
        guid=guid[:1000], url=url, title=unescape(title).strip()[:MAX_TITLE],
        summary=summary[:MAX_SUMMARY], published_at=_date(date), links=links,
    )


def _rss2(channel: Element) -> list[FeedEntry]:
    out = []
    for item in channel.findall("item"):
        url = _clean_url(_text(item.find("link")))
        body = _text(item.find("content:encoded", NS)) or _text(item.find("description"))
        date = _text(item.find("pubDate")) or _text(item.find("dc:date", NS))
        e = _entry(_text(item.find("guid")), url, _text(item.find("title")), body, date)
        if e:
            out.append(e)
    return out


def _rss1(root: Element) -> list[FeedEntry]:
    out = []
    for item in root.findall("rss1:item", NS):
        url = _clean_url(_text(item.find("rss1:link", NS)) or item.get(f"{{{NS['rdf']}}}about"))
        body = _text(item.find("content:encoded", NS)) or _text(item.find("rss1:description", NS))
        e = _entry(item.get(f"{{{NS['rdf']}}}about") or "", url, _text(item.find("rss1:title", NS)), body,
                   _text(item.find("dc:date", NS)))
        if e:
            out.append(e)
    return out


def _atom(root: Element) -> list[FeedEntry]:
    out = []
    for item in root.findall("atom:entry", NS):
        links = item.findall("atom:link", NS)
        alt = next((lk for lk in links if lk.get("rel", "alternate") == "alternate"), links[0] if links else None)
        url = _clean_url(alt.get("href") if alt is not None else None)
        body = _text(item.find("atom:content", NS)) or _text(item.find("atom:summary", NS))
        date = _text(item.find("atom:published", NS)) or _text(item.find("atom:updated", NS))
        e = _entry(_text(item.find("atom:id", NS)), url, _text(item.find("atom:title", NS)), body, date)
        if e:
            out.append(e)
    return out


def parse_feed(body: bytes) -> list[FeedEntry]:
    """新しい順に MAX_ENTRIES 件まで。形式が分からなければ InvalidFeed。"""
    try:
        root = SafeET.fromstring(body, forbid_dtd=True)
    except Exception as e:  # defusedxml の拒否 (DTD・実体) と XML の構文エラー
        raise InvalidFeed(f"{type(e).__name__}: {e}") from None
    parsers: dict[str, Callable[[], list[FeedEntry]]] = {
        "rss": lambda: _rss2(root.find("channel") if root.find("channel") is not None else root),
        f"{{{NS['rdf']}}}RDF": lambda: _rss1(root),
        f"{{{NS['atom']}}}feed": lambda: _atom(root),
    }
    if root.tag not in parsers:
        raise InvalidFeed(f"unknown feed root element: {root.tag}")
    entries = parsers[root.tag]()
    entries.sort(key=lambda e: e.published_at or "", reverse=True)
    return entries[:MAX_ENTRIES]
