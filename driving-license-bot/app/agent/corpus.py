"""法令 / 教則の grounding コーパス（Phase 2-B はスタブ）。

Phase 2-B: 道路交通法の主要条文を hardcode した最小辞書。category × topic_hint
で関連スニペットを返す。

Phase 4 (law-update-pipeline) で e-Gov API から取得した snapshot を読む実装に
差し替える。本ファイルの `pick_snippets` の戻り値型さえ変えなければ、Question
Generator 側は無変更で済む。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CorpusSnippet:
    """LLM プロンプトに埋め込む grounding 用スニペット。"""

    title: str
    url: str
    text: str  # 1〜3 文程度の要約引用


# 道路交通法の主要条文（学科試験頻出ジャンル別）。
# Phase 4 で e-Gov API 連携に置き換え、ここは emergency fallback とする。
_LAW_BASE = "https://laws.e-gov.go.jp/document?lawid=335AC0000000105"
_ENF_ORDER = "https://laws.e-gov.go.jp/document?lawid=335CO0000000270"
_SIGN_ORDER = "https://laws.e-gov.go.jp/document?lawid=335M50000003003"
_KYOUSOKU = "https://www.npa.go.jp/bureau/traffic/20241113kyousoku.pdf"


_CORPUS: dict[str, list[CorpusSnippet]] = {
    "rules": [
        CorpusSnippet(
            title="道路交通法 第 38 条（横断歩道等における歩行者等の優先）",
            url=_LAW_BASE,
            text=(
                "車両等が横断歩道に接近する場合に横断しようとする歩行者があるときは、"
                "その手前で一時停止し、かつ、その通行を妨げないようにしなければならない。"
            ),
        ),
        CorpusSnippet(
            title="道路交通法 第 43 条（指定場所における一時停止）",
            url=_LAW_BASE,
            text=(
                "一時停止の標識・標示のある場所では停止線の直前で一時停止し、"
                "交差道路を通行する車両等の進行を妨げてはならない。"
            ),
        ),
        CorpusSnippet(
            title="道路交通法施行令 第 11 条（最高速度）",
            url=_ENF_ORDER,
            text="一般道路における自動車の法定最高速度は時速 60 キロメートル。",
        ),
        CorpusSnippet(
            title="道路交通法 第 65 条（酒気帯び運転等の禁止）",
            url=_LAW_BASE,
            text="何人も酒気を帯びて車両等を運転してはならない。",
        ),
        CorpusSnippet(
            title="道路交通法 第 26 条（車間距離の保持）",
            url=_LAW_BASE,
            text=(
                "車両は前車が急停止したときでも追突を避けることができる安全な車間"
                "距離を保たなければならない。"
            ),
        ),
        CorpusSnippet(
            title="道路交通法施行令 第 27 条（高速自動車国道での最高速度）",
            url=_ENF_ORDER,
            text="高速自動車国道の本線車道における普通自動車の法定最高速度は時速 100 キロメートル。",
        ),
    ],
    "signs": [
        CorpusSnippet(
            title="道路標識、区画線及び道路標示に関する命令 別表第二（規制標識）",
            url=_SIGN_ORDER,
            text=(
                "規制標識は、特定の交通方法を禁止又は指定する標識。一時停止・"
                "車両進入禁止・最高速度・駐車禁止などが含まれる。"
            ),
        ),
    ],
    "manners": [
        CorpusSnippet(
            title="道路交通法 第 71 条の 3（運転者の遵守事項：シートベルト）",
            url=_LAW_BASE,
            text=(
                "運転者は座席ベルトを装着し、助手席・後部座席の同乗者にも装着"
                "させなければならない。"
            ),
        ),
        CorpusSnippet(
            title="道路交通法 第 72 条（交通事故の場合の措置）",
            url=_LAW_BASE,
            text=(
                "交通事故があったときは運転者等は直ちに運転を停止し、負傷者の救護"
                "と危険防止の措置をとり、警察官に報告しなければならない。"
            ),
        ),
    ],
    "hazard": [
        CorpusSnippet(
            title="交通の方法に関する教則 — 危険予測",
            url=_KYOUSOKU,
            text=(
                "雨天・夜間・路面凍結等の悪条件では制動距離が伸び、視界も悪くなる"
                "ため、通常時より十分な車間距離と低速度が必要。"
            ),
        ),
        CorpusSnippet(
            title="道路交通法 第 52 条第 2 項（車両等の灯火）",
            url=_LAW_BASE,
            text=(
                "対向車と行き違うときや前車に追従するときは、前照灯を下向きに"
                "切り替える等まぶしさを与えないようにしなければならない。"
            ),
        ),
    ],
}


def pick_snippets(category: str, *, limit: int = 4) -> list[CorpusSnippet]:
    """カテゴリに紐づくスニペットを最大 `limit` 件返す。

    Phase 2-B はカテゴリ固定の辞書ベース。Phase 4 で topic_hint からの
    embedding 検索（pgvector）に置き換える。
    """
    snippets = _CORPUS.get(category, [])
    if not snippets:
        # 学科試験全般のため rules を fallback として返す
        snippets = _CORPUS.get("rules", [])
    return snippets[:limit]


def all_categories() -> list[str]:
    return sorted(_CORPUS.keys())


__all__ = ["CorpusSnippet", "all_categories", "pick_snippets"]
