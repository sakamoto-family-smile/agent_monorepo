"""URL pattern ベース category 分類器のテスト。"""

from __future__ import annotations

import pytest

from fujisawa_platform.etl._category_classifier import classify_category


@pytest.mark.parametrize(
    "url,expected",
    [
        # garbage
        ("https://www.city.fujisawa.kanagawa.jp/kurashi/gomi/index.html", "garbage"),
        ("https://www.city.fujisawa.kanagawa.jp/kurashi/gomi/wakekata/index.html", "garbage"),
        ("https://www.city.fujisawa.kanagawa.jp/kankyou-s/kurashi/gomi/shisaku/kihonjore.html", "garbage"),
        ("https://www.city.fujisawa.kanagawa.jp/kurashi/gomi/recycle/jidosha/index.html", "garbage"),
        # disaster (各 keyword variant)
        ("https://www.city.fujisawa.kanagawa.jp/bosai/bosai/index.html", "disaster"),
        ("https://www.city.fujisawa.kanagawa.jp/bosai/shobo/tsuho/index.html", "disaster"),
        ("https://www.city.fujisawa.kanagawa.jp/bosai/kikikanri/index.html", "disaster"),
        ("https://www.city.fujisawa.kanagawa.jp/bosai/bohan/index.html", "disaster"),
        ("https://www.city.fujisawa.kanagawa.jp/bouhan/bosai/index.html", "disaster"),
        # parenting
        ("https://www.city.fujisawa.kanagawa.jp/hoiku/kenko/kosodate/hoikuen/ninka-ichiran.html", "parenting"),
        ("https://www.city.fujisawa.kanagawa.jp/kosodatekyouiku/kenko/kosodate/index.html", "parenting"),
        ("https://www.city.fujisawa.kanagawa.jp/jido-c/kenko/kosodate/index.html", "parenting"),
        # procedure
        ("https://www.city.fujisawa.kanagawa.jp/mado-c/kurashi/koseki/index.html", "procedure"),
        ("https://www.city.fujisawa.kanagawa.jp/jumin/kurashi/index.html", "procedure"),
        ("https://www.city.fujisawa.kanagawa.jp/koseki/kurashi/index.html", "procedure"),
        # tourism
        ("https://www.city.fujisawa.kanagawa.jp/kouen/kyoiku/leisure/koen/index.html", "tourism"),
        ("https://www.city.fujisawa.kanagawa.jp/kanko/index.html", "tourism"),
        # cityhall
        ("https://www.city.fujisawa.kanagawa.jp/kouhou/shise/koho/catv/index.html", "cityhall"),
        ("https://www.city.fujisawa.kanagawa.jp/shise/gaiyo/shicho/kishakaiken/2023/index.html", "cityhall"),
        ("https://www.city.fujisawa.kanagawa.jp/kikaku/shise/kekaku/sesaku/sdgs/index.html", "cityhall"),
        ("https://www.city.fujisawa.kanagawa.jp/zaisei/shise/index.html", "cityhall"),
        # 未知 / 上記いずれにも該当しない
        ("https://www.city.fujisawa.kanagawa.jp/manabi/kyoiku/index.html", None),
        ("https://www.city.fujisawa.kanagawa.jp/honen/nenkin/index.html", None),
        ("", None),
    ],
)
def test_classify_category(url: str, expected: str | None) -> None:
    assert classify_category(url) == expected


class TestPriority:
    """優先度順位の検証 (garbage > disaster > parenting > procedure > tourism > cityhall)。"""

    def test_garbage_wins_over_other_keywords(self) -> None:
        # ありえないが念のため: gomi (garbage) と bosai (disaster) が両方含まれる URL
        url = "https://www.city.fujisawa.kanagawa.jp/bosai/gomi/index.html"
        assert classify_category(url) == "garbage"

    def test_disaster_wins_over_parenting(self) -> None:
        url = "https://www.city.fujisawa.kanagawa.jp/bosai/hoiku/index.html"
        assert classify_category(url) == "disaster"

    def test_parenting_wins_over_cityhall(self) -> None:
        url = "https://www.city.fujisawa.kanagawa.jp/hoiku/shise/index.html"
        assert classify_category(url) == "parenting"
