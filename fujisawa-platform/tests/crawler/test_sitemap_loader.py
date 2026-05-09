"""SitemapLoader のテスト。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from fujisawa_platform.crawler.sitemap_loader import (
    SitemapEntry,
    SitemapParseError,
    parse_sitemap,
)

FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "sample_sitemap.xml"
)


class TestParseSitemap:
    def test_parses_all_urls(self) -> None:
        """fixture から 5 URL 抽出。"""
        entries = parse_sitemap(FIXTURE.read_bytes())
        assert len(entries) == 5

    def test_returns_sitemap_entries(self) -> None:
        """各エントリは SitemapEntry。"""
        entries = parse_sitemap(FIXTURE.read_bytes())
        assert all(isinstance(e, SitemapEntry) for e in entries)

    def test_extracts_loc_in_order(self) -> None:
        """URL 出現順を保つ。"""
        entries = parse_sitemap(FIXTURE.read_bytes())
        urls = [str(e.url) for e in entries]
        assert urls[0] == "https://www.city.fujisawa.kanagawa.jp/"
        assert urls[1] == "https://www.city.fujisawa.kanagawa.jp/bosai/index.html"
        assert (
            urls[2]
            == "https://www.city.fujisawa.kanagawa.jp/hoiku/kenko/kosodate/hoikuen/ninka-ichiran.html"
        )

    def test_parses_date_only_lastmod(self) -> None:
        """`<lastmod>2026-05-01</lastmod>` を date として読む。"""
        entries = parse_sitemap(FIXTURE.read_bytes())
        root = entries[0]
        assert root.lastmod == date(2026, 5, 1)

    def test_parses_iso_datetime_lastmod(self) -> None:
        """`<lastmod>2026-04-15T03:00:00+09:00</lastmod>` を date 部分のみ取る。"""
        entries = parse_sitemap(FIXTURE.read_bytes())
        ninka = next(e for e in entries if "ninka-ichiran" in str(e.url))
        assert ninka.lastmod == date(2026, 4, 15)

    def test_lastmod_absent_returns_none(self) -> None:
        """`<lastmod>` がない URL は lastmod=None。"""
        entries = parse_sitemap(FIXTURE.read_bytes())
        bosai = next(e for e in entries if "bosai" in str(e.url))
        assert bosai.lastmod is None

    def test_handles_namespace_correctly(self) -> None:
        """sitemap.org namespace 付きでも parse できる。"""
        # fixture が xmlns 付き → 既に検証済
        entries = parse_sitemap(FIXTURE.read_bytes())
        assert len(entries) > 0


class TestParseSitemapErrors:
    def test_invalid_xml_raises(self) -> None:
        """壊れた XML は SitemapParseError。"""
        with pytest.raises(SitemapParseError):
            parse_sitemap(b"<not-xml")

    def test_non_sitemap_xml_raises(self) -> None:
        """sitemap でない XML は SitemapParseError。"""
        bad = b'<?xml version="1.0"?><root></root>'
        with pytest.raises(SitemapParseError):
            parse_sitemap(bad)

    def test_empty_urlset_returns_empty_list(self) -> None:
        """`<urlset>` が空でも error にはせず空 list を返す。"""
        empty = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
        )
        assert parse_sitemap(empty) == []


class TestSitemapEntry:
    def test_immutable(self) -> None:
        entry = SitemapEntry(
            url="https://www.city.fujisawa.kanagawa.jp/",
            lastmod=date(2026, 5, 1),
        )
        # frozen Pydantic model
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            entry.lastmod = date(2026, 1, 1)  # type: ignore[misc]

    def test_lastmod_can_accept_datetime_or_none(self) -> None:
        """lastmod が datetime で渡されても date に揃える。"""
        entry = SitemapEntry(
            url="https://www.city.fujisawa.kanagawa.jp/",
            lastmod=datetime(2026, 5, 1, 12, 0),
        )
        assert entry.lastmod == date(2026, 5, 1)
