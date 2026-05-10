"""緊急情報 RSS の parse helper。

藤沢市 緊急情報 RSS を LINE bot (proposal 0004) の Emergency Agent が 5 分間隔で poll する。
poll の loop / 重複検知 (seen_guids) は LINE bot 側 (`fujisawa-info-bot/batch/poll_rss.py`) に
持たせ、本基盤は **「bytes → list[RssEntry]」の純粋な parse 関数のみ** を提供する
(proposal 0003 §4.5.4 の方針)。

設計上の選択:
- RSS 2.0 / Atom の **両方** を parse_feed() で扱う
  - 藤沢市 HP がどちらを返すか実機確認できていないため、両対応にしておく
- defusedxml で XXE / billion laughs を防止 (sitemap_loader と同じ手法)
- guid / id 不在時は link を一意キーとして使う
- pubDate 不正は entry を捨てず published=None にフォールバック

非対応:
- HTTP fetch (`PoliteFetcher` を consumer 側で噛ます。本モジュールは parse のみ)
- 5 分 poll loop (proposal 0003 §4.5.4 の方針で LINE bot 側)
- guid 重複排除 (consumer 側で `seen_guids` セット運用する)
"""

from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET  # 型のみ参照 (parse は defusedxml)

from defusedxml import ElementTree as DET
from defusedxml.common import DefusedXmlException
from pydantic import BaseModel, ConfigDict, HttpUrl

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


class RssParseError(ValueError):
    """RSS / Atom feed の parse に失敗。"""


class RssEntry(BaseModel):
    """RSS 2.0 `<item>` または Atom `<entry>` を統一表現に正規化したもの。

    `guid` は consumer 側で重複検知するための一意キー。RSS の `<guid>`、
    Atom の `<id>`、どちらも欠ける場合は link をそのまま使う。
    """

    model_config = ConfigDict(frozen=True)

    guid: str
    title: str
    link: HttpUrl
    published: datetime | None = None
    summary: str | None = None


def parse_feed(content: bytes) -> list[RssEntry]:
    """RSS 2.0 または Atom feed を parse して entry のリストを返す。

    Args:
        content: feed の生 bytes (HTTP レスポンスボディ)。

    Returns:
        feed に含まれる item / entry の出現順リスト。重複排除はしない。

    Raises:
        RssParseError: XML が壊れている / ルート要素が rss でも feed でもない /
            `<item>` 内に必須要素 (title / link) が欠落。
    """
    try:
        root = DET.fromstring(content)
    except (ET.ParseError, DefusedXmlException) as err:
        raise RssParseError(f"invalid XML: {err}") from err

    localname = _localname(root.tag)
    if localname == "rss":
        return _parse_rss20(root)
    if localname == "feed":
        return _parse_atom(root)
    raise RssParseError(f"unknown feed root element: <{root.tag}>")


def _parse_rss20(root: ET.Element) -> list[RssEntry]:
    """RSS 2.0: `<rss><channel><item>...</item></channel></rss>`."""
    channel = root.find("channel")
    if channel is None:
        return []

    entries: list[RssEntry] = []
    for item in channel.findall("item"):
        title = _text(item, "title")
        link = _text(item, "link")
        if title is None:
            raise RssParseError("<item> without <title>")
        if link is None:
            raise RssParseError("<item> without <link>")
        guid = _text(item, "guid") or link
        summary = _text(item, "description")
        published = _parse_rfc822(_text(item, "pubDate"))
        entries.append(
            RssEntry(
                guid=guid,
                title=title,
                link=link,
                published=published,
                summary=summary,
            )
        )
    return entries


def _parse_atom(root: ET.Element) -> list[RssEntry]:
    """Atom: `<feed><entry>...</entry></feed>`."""
    entries: list[RssEntry] = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        title = _text(entry, "atom:title", _ATOM_NS)
        if title is None:
            raise RssParseError("<entry> without <title>")
        link = _atom_link(entry)
        if link is None:
            raise RssParseError("<entry> without <link>")
        guid = _text(entry, "atom:id", _ATOM_NS) or link
        summary = _text(entry, "atom:summary", _ATOM_NS)
        published = _parse_iso8601(
            _text(entry, "atom:updated", _ATOM_NS) or _text(entry, "atom:published", _ATOM_NS)
        )
        entries.append(
            RssEntry(
                guid=guid,
                title=title,
                link=link,
                published=published,
                summary=summary,
            )
        )
    return entries


def _atom_link(entry: ET.Element) -> str | None:
    """Atom `<link>` の href 属性を返す。rel="alternate" を優先。

    複数の `<link>` があった場合 (rel=self / rel=alternate / etc.) は
    rel="alternate" を最優先、無ければ rel 属性なしの link、それも無ければ最初の link。
    """
    links = entry.findall("atom:link", _ATOM_NS)
    if not links:
        return None
    alternate = next(
        (link for link in links if link.get("rel") == "alternate"),
        None,
    )
    if alternate is not None:
        return alternate.get("href")
    no_rel = next((link for link in links if link.get("rel") is None), None)
    if no_rel is not None:
        return no_rel.get("href")
    return links[0].get("href")


def _text(elem: ET.Element, path: str, ns: dict[str, str] | None = None) -> str | None:
    """子要素のテキストを取得。空白のみは None として扱う。"""
    found = elem.find(path, ns) if ns else elem.find(path)
    if found is None or found.text is None:
        return None
    text = found.text.strip()
    return text or None


def _parse_rfc822(value: str | None) -> datetime | None:
    """`<pubDate>Wed, 06 May 2026 06:00:00 +0900</pubDate>` を datetime に。"""
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _parse_iso8601(value: str | None) -> datetime | None:
    """Atom の `<updated>2026-05-06T06:00:00+09:00</updated>` を datetime に。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _localname(tag: str) -> str:
    """`{ns}local` 形式から localname を取り出す。"""
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag
