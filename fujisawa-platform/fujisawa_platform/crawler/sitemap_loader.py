"""sitemap.xml parser。

藤沢市 HP の sitemap.xml は約 1,100+ URL を含む (proposal 0003 §3.2 / 調査 §A3-2)。
LINE bot (proposal 0004) の `weekly_crawl_etl` でクロール起点として利用する。

設計上の選択:
- 標準 lxml の iterparse ではなく ElementTree で parse (1,100 URL なら memory に乗る)
- `<lastmod>` は date / datetime 両対応、欠落時は None
- 不正な XML は SitemapParseError で raise
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from xml.etree import ElementTree as ET  # 型のみ参照 (parse は defusedxml)

from defusedxml import ElementTree as DET
from defusedxml.common import DefusedXmlException
from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator

_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


class SitemapParseError(ValueError):
    """sitemap.xml の parse に失敗。"""


class SitemapEntry(BaseModel):
    """sitemap.xml の `<url>` 要素。"""

    model_config = ConfigDict(frozen=True)

    url: HttpUrl
    lastmod: date | None = None

    @field_validator("lastmod", mode="before")
    @classmethod
    def _normalize_lastmod(cls, v: Any) -> date | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        if isinstance(v, str):
            return _parse_lastmod_string(v)
        raise ValueError(f"unsupported lastmod type: {type(v).__name__}")


def parse_sitemap(content: bytes) -> list[SitemapEntry]:
    """sitemap.xml の bytes を parse して `<url>` リストを返す。

    Args:
        content: sitemap.xml のバイト列。

    Returns:
        `<url>` 要素ごとの `SitemapEntry` のリスト (出現順)。

    Raises:
        SitemapParseError: XML が壊れている / `<urlset>` ルートでない / 必須要素が欠落。
    """
    try:
        # defusedxml.ElementTree.fromstring は XXE / billion laughs を防ぐ。
        # 戻り値は標準 xml.etree の Element 互換なので以降のロジックはそのまま。
        root = DET.fromstring(content)
    except (ET.ParseError, DefusedXmlException) as err:
        raise SitemapParseError(f"invalid XML: {err}") from err

    if not _localname(root.tag) == "urlset":
        raise SitemapParseError(f"root element is not <urlset>: got <{root.tag}>")

    entries: list[SitemapEntry] = []
    for url_elem in root.findall("sm:url", _NS):
        loc_elem = url_elem.find("sm:loc", _NS)
        if loc_elem is None or loc_elem.text is None:
            raise SitemapParseError("<url> without <loc>")
        loc = loc_elem.text.strip()
        lastmod_elem = url_elem.find("sm:lastmod", _NS)
        lastmod_raw = (
            lastmod_elem.text.strip()
            if lastmod_elem is not None and lastmod_elem.text is not None
            else None
        )
        entries.append(SitemapEntry(url=loc, lastmod=lastmod_raw))
    return entries


def _localname(tag: str) -> str:
    """`{ns}local` 形式から localname を取り出す。"""
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _parse_lastmod_string(value: str) -> date | None:
    """`<lastmod>` の文字列を date に。"""
    value = value.strip()
    if not value:
        return None
    # ISO 8601 datetime (e.g. "2026-04-15T03:00:00+09:00")
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        pass
    # date only (e.g. "2026-05-01")
    try:
        return date.fromisoformat(value)
    except ValueError as err:
        raise ValueError(f"invalid lastmod: {value!r}") from err
