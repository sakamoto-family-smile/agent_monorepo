"""pages.category 自動付与のための URL pattern ベース分類器。

`weekly_crawl_etl` が藤沢市 HP の各 URL を fetch する際に `classify_category()`
で category を決定し、 `pages.category` カラムに保存する。 これを Intent agent
(fujisawa-info-bot) の category フィルタが使う。

ラベル一覧 (fujisawa-info-bot/app/skills/category_routing.md と同期):
- `disaster`  防災 / 安全 / 火災 / 危機管理
- `parenting` 保育 / 子育て / 児童 / 教育
- `garbage`   ごみ / リサイクル / 環境衛生
- `procedure` 手続き / 住民票 / マイナンバー / 窓口
- `tourism`   観光 / 公園 / レジャー / スポーツ
- `cityhall`  市政 / 広報 / 記者会見 / 計画
- `None`      上記いずれにも該当しない (Intent 側で `other` に対応)

設計判断 (2026-05-22):
- 藤沢市 URL は `/<top>/<sub>/<path>/index.html` 構造で、 top と sub に
  上記キーワードが現れる (cross-prefix 構造: 例 `/kankyou-s/kurashi/gomi/...`)
- 単一 first-segment match では取りこぼすため、 全 URL パスから keyword
  substring を検索する
- 優先順位: garbage > disaster > parenting > procedure > tourism > cityhall
  (specific → general)
- LLM 不要・SQL の UPDATE で backfill 可能 (URL → category の純粋関数)
"""

from __future__ import annotations

from typing import Final

# 優先度順 (上位ほど specific)。 keyword は path segment 内に部分一致で含まれていれば
# match と判定する。
_RULES: Final[list[tuple[str, list[str]]]] = [
    # garbage / ごみ・リサイクル
    (
        "garbage",
        ["gomi", "recycle"],
    ),
    # disaster / 防災 / 安全 / 危機管理
    (
        "disaster",
        ["bosai", "bousai", "bouhan", "bohan", "saigai", "shobo", "kikikanri"],
    ),
    # parenting / 保育・子育て・児童
    (
        "parenting",
        [
            "hoiku",
            "kosodate",
            "kosodatekyouiku",
            "youchien",
            "jido",
            "kosodateshienin",
        ],
    ),
    # procedure / 手続き・住民票・マイナンバー・窓口
    (
        "procedure",
        ["tetsuduki", "jumin", "koseki", "mynumber", "mado-c"],
    ),
    # tourism / 観光 / 公園 / レジャー / スポーツ
    (
        "tourism",
        ["kanko", "kankou", "kankoshinko", "kouen", "leisure"],
    ),
    # cityhall / 市政・広報・計画・記者会見
    (
        "cityhall",
        ["shise", "kouhou", "kishakaiken", "kikaku", "zaisei", "koho"],
    ),
]


def classify_category(url: str) -> str | None:
    """URL から category を推定する。

    優先度順に keyword substring を検索し、 最初にヒットした category を返す。
    何にも該当しなければ `None` (Intent agent 側で "other" 扱い)。

    Examples:
        >>> classify_category("https://www.city.fujisawa.kanagawa.jp/kurashi/gomi/wakekata/index.html")
        'garbage'
        >>> classify_category("https://www.city.fujisawa.kanagawa.jp/bosai/bosai/index.html")
        'disaster'
        >>> classify_category("https://www.city.fujisawa.kanagawa.jp/hoiku/kenko/.../ninka.html")
        'parenting'
        >>> classify_category("https://www.city.fujisawa.kanagawa.jp/foo/bar/baz.html")  # 未知
    """
    if not url:
        return None
    # URL を小文字化して keyword と比較 (path segment は元々小文字なので冗長だが安全)
    lowered = url.lower()
    for category, keywords in _RULES:
        if any(kw in lowered for kw in keywords):
            return category
    return None


__all__ = ["classify_category"]
