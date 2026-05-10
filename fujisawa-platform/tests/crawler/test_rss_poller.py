"""rss_poller のテスト。

藤沢市 緊急情報 RSS (LINE bot proposal 0004 §3 で利用) の parse 仕様:

- RSS 2.0 / Atom 両対応 (源によってどちらが返るか不明なため、両方サポート)
- `<guid>` (RSS) / `<id>` (Atom) を一意キーとして抽出 (consumer 側で重複検知に使う)
- 必須要素: link / title (どちらか欠けたら entry を skip ではなく parse error)
- 不正 XML は RssParseError (defusedxml で XXE / billion laughs 対策済)
- 5 分 poll 自体は LINE bot 側 (`fujisawa-info-bot/batch/poll_rss.py`) に実装する想定
  本モジュールは parse helper のみ提供
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fujisawa_platform.crawler.rss_poller import (
    RssEntry,
    RssParseError,
    parse_feed,
)


def _rss20(items_xml: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>藤沢市 緊急情報</title>
    <link>https://www.city.fujisawa.kanagawa.jp/</link>
    <description>緊急情報フィード</description>
    {items_xml}
  </channel>
</rss>""".encode()


def _atom(entries_xml: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>藤沢市 緊急情報</title>
  <link href="https://www.city.fujisawa.kanagawa.jp/" />
  <updated>2026-05-10T00:00:00+09:00</updated>
  {entries_xml}
</feed>""".encode()


class TestRss20:
    def test_parses_single_item(self) -> None:
        content = _rss20(
            """<item>
                <title>豪雨警報</title>
                <link>https://www.city.fujisawa.kanagawa.jp/news/1</link>
                <description>本日 15:00 発表</description>
                <pubDate>Wed, 06 May 2026 06:00:00 +0900</pubDate>
                <guid isPermaLink="false">emergency-2026-05-06-001</guid>
            </item>"""
        )
        entries = parse_feed(content)
        assert len(entries) == 1
        e = entries[0]
        assert e.guid == "emergency-2026-05-06-001"
        assert e.title == "豪雨警報"
        assert str(e.link) == "https://www.city.fujisawa.kanagawa.jp/news/1"
        assert e.summary == "本日 15:00 発表"
        assert e.published is not None
        assert e.published.year == 2026
        assert e.published.month == 5
        assert e.published.day == 6

    def test_parses_multiple_items_in_order(self) -> None:
        content = _rss20(
            """<item>
                <title>A</title>
                <link>https://www.city.fujisawa.kanagawa.jp/a</link>
                <guid>id-a</guid>
            </item>
            <item>
                <title>B</title>
                <link>https://www.city.fujisawa.kanagawa.jp/b</link>
                <guid>id-b</guid>
            </item>"""
        )
        entries = parse_feed(content)
        assert [e.guid for e in entries] == ["id-a", "id-b"]

    def test_falls_back_to_link_when_guid_missing(self) -> None:
        """`<guid>` 不在時は `<link>` を guid として扱う。"""
        content = _rss20(
            """<item>
                <title>guid なし</title>
                <link>https://www.city.fujisawa.kanagawa.jp/x</link>
            </item>"""
        )
        entries = parse_feed(content)
        assert len(entries) == 1
        assert entries[0].guid == "https://www.city.fujisawa.kanagawa.jp/x"

    def test_published_optional(self) -> None:
        content = _rss20(
            """<item>
                <title>日付なし</title>
                <link>https://www.city.fujisawa.kanagawa.jp/x</link>
                <guid>x</guid>
            </item>"""
        )
        entries = parse_feed(content)
        assert entries[0].published is None

    def test_invalid_pubdate_returns_none(self) -> None:
        """不正な pubDate は None にフォールバック (entry 自体は parse 続行)。"""
        content = _rss20(
            """<item>
                <title>不正日付</title>
                <link>https://www.city.fujisawa.kanagawa.jp/x</link>
                <guid>x</guid>
                <pubDate>not-a-date</pubDate>
            </item>"""
        )
        entries = parse_feed(content)
        assert entries[0].published is None

    def test_empty_channel_returns_empty_list(self) -> None:
        content = _rss20("")
        entries = parse_feed(content)
        assert entries == []


class TestAtom:
    def test_parses_single_entry(self) -> None:
        content = _atom(
            """<entry>
                <id>urn:fujisawa:emergency:2026-05-06-001</id>
                <title>豪雨警報</title>
                <link href="https://www.city.fujisawa.kanagawa.jp/news/1" />
                <updated>2026-05-06T06:00:00+09:00</updated>
                <summary>本日 15:00 発表</summary>
            </entry>"""
        )
        entries = parse_feed(content)
        assert len(entries) == 1
        e = entries[0]
        assert e.guid == "urn:fujisawa:emergency:2026-05-06-001"
        assert e.title == "豪雨警報"
        assert str(e.link) == "https://www.city.fujisawa.kanagawa.jp/news/1"
        assert e.summary == "本日 15:00 発表"
        assert e.published is not None

    def test_atom_link_with_rel_alternate_preferred(self) -> None:
        """rel="alternate" の link を優先して採用する。"""
        content = _atom(
            """<entry>
                <id>id-1</id>
                <title>T</title>
                <link rel="self" href="https://www.city.fujisawa.kanagawa.jp/feed" />
                <link rel="alternate" href="https://www.city.fujisawa.kanagawa.jp/news/1" />
                <updated>2026-05-06T06:00:00+09:00</updated>
            </entry>"""
        )
        entries = parse_feed(content)
        assert str(entries[0].link) == "https://www.city.fujisawa.kanagawa.jp/news/1"

    def test_summary_optional(self) -> None:
        content = _atom(
            """<entry>
                <id>id-1</id>
                <title>T</title>
                <link href="https://www.city.fujisawa.kanagawa.jp/news/1" />
                <updated>2026-05-06T06:00:00+09:00</updated>
            </entry>"""
        )
        entries = parse_feed(content)
        assert entries[0].summary is None

    def test_atom_published_parsed_to_utc_aware_datetime(self) -> None:
        content = _atom(
            """<entry>
                <id>id-1</id>
                <title>T</title>
                <link href="https://www.city.fujisawa.kanagawa.jp/news/1" />
                <updated>2026-05-06T06:00:00+09:00</updated>
            </entry>"""
        )
        entries = parse_feed(content)
        published = entries[0].published
        assert published is not None
        assert published.tzinfo is not None
        # +09:00 → UTC は前日 21:00
        utc = published.astimezone(UTC)
        assert utc.hour == 21
        assert utc.day == 5


class TestErrors:
    def test_invalid_xml_raises(self) -> None:
        with pytest.raises(RssParseError):
            parse_feed(b"<not really xml")

    def test_unknown_root_raises(self) -> None:
        content = b"<?xml version='1.0'?><html><body>nope</body></html>"
        with pytest.raises(RssParseError, match="root"):
            parse_feed(content)

    def test_item_without_link_raises(self) -> None:
        content = _rss20(
            """<item>
                <title>link なし</title>
                <guid>x</guid>
            </item>"""
        )
        with pytest.raises(RssParseError, match="link"):
            parse_feed(content)

    def test_item_without_title_raises(self) -> None:
        content = _rss20(
            """<item>
                <link>https://www.city.fujisawa.kanagawa.jp/x</link>
                <guid>x</guid>
            </item>"""
        )
        with pytest.raises(RssParseError, match="title"):
            parse_feed(content)


class TestDeduplication:
    """consumer 側で `seen_guids` セット運用するための前提を確認するテスト。

    parse_feed 自体は重複排除しない (raw を返す)。consumer が guid を見て
    `if entry.guid not in seen:` で判定する。
    """

    def test_duplicate_guids_returned_as_is(self) -> None:
        content = _rss20(
            """<item>
                <title>A</title>
                <link>https://www.city.fujisawa.kanagawa.jp/a</link>
                <guid>same</guid>
            </item>
            <item>
                <title>A again</title>
                <link>https://www.city.fujisawa.kanagawa.jp/a</link>
                <guid>same</guid>
            </item>"""
        )
        entries = parse_feed(content)
        assert len(entries) == 2
        assert entries[0].guid == entries[1].guid == "same"


class TestRssEntryModel:
    def test_frozen(self) -> None:
        e = RssEntry(
            guid="x",
            title="t",
            link="https://www.city.fujisawa.kanagawa.jp/x",
            published=datetime(2026, 5, 6, 6, 0, tzinfo=UTC),
            summary=None,
        )
        with pytest.raises(Exception):
            e.guid = "y"  # type: ignore[misc]
