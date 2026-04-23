"""食材名 → 正規化タグへの変換。

ユーザー入力は揺れる:
  - 表記ゆれ: "じゃがいも" / "ジャガイモ" / "じゃが芋" / "馬鈴薯" / "potato"
  - 部位違い: "鶏もも肉" / "鶏むね肉" → どちらも tag は "toriniku" (Phase 1 は粗い粒度)
  - 不要記号: "★" / "(冷蔵)" 等

設計:
  - エイリアス辞書 → 直接ヒットすれば最優先
  - rapidfuzz による曖昧マッチをフォールバック (短い食材名でも誤爆しないよう閾値高め)
  - 未解決は元の文字列を tag 化 (lowercase + 空白除去) して残す
    (catalog 側にもヒットしない可能性が高いが、デバッグログ可能)
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import process as fuzz_process

logger = logging.getLogger(__name__)


# Phase 1 シードでカバーする食材タグ。menu-catalog.json の ingredient_tags と
# 1:1 で揃える (この辞書に無いタグは catalog にも無いはず)。
INGREDIENT_ALIASES: dict[str, list[str]] = {
    # 野菜
    "jagaimo":   ["じゃがいも", "ジャガイモ", "じゃが芋", "馬鈴薯", "potato", "メークイン", "男爵"],
    "tamanegi":  ["玉ねぎ", "タマネギ", "玉葱", "たまねぎ", "onion"],
    "ninjin":    ["にんじん", "ニンジン", "人参", "carrot"],
    "kabocha":   ["かぼちゃ", "カボチャ", "南瓜", "pumpkin"],
    "daikon":    ["大根", "だいこん", "ダイコン", "radish", "白首大根"],
    "hakusai":   ["白菜", "はくさい", "ハクサイ", "chinese cabbage"],
    "kyabetsu":  ["キャベツ", "きゃべつ", "cabbage"],
    "renkon":    ["れんこん", "レンコン", "蓮根"],
    "gobou":     ["ごぼう", "ゴボウ", "牛蒡"],
    "satsumaimo":["さつまいも", "サツマイモ", "薩摩芋", "甘藷", "sweet potato"],
    "negi":      ["ねぎ", "ネギ", "葱", "長ねぎ", "青ねぎ", "万能ねぎ"],
    "tomato":    ["トマト", "とまと", "tomato", "ホールトマト", "カットトマト"],
    "nasu":      ["なす", "ナス", "茄子", "eggplant"],
    "zucchini":  ["ズッキーニ", "ずっきーに", "zucchini"],
    "piman":     ["ピーマン", "ぴーまん", "bell pepper", "パプリカ"],
    "shimeji":   ["しめじ", "シメジ", "占地"],
    "shiitake":  ["しいたけ", "シイタケ", "椎茸"],
    "enoki":     ["えのき", "エノキ", "榎茸"],
    "maitake":   ["まいたけ", "マイタケ", "舞茸"],

    # 肉・魚
    "gyuniku":   ["牛肉", "ぎゅうにく", "ビーフ", "beef", "牛切り落とし", "牛こま"],
    "butaniku":  ["豚肉", "ぶたにく", "ポーク", "pork", "豚バラ", "豚こま", "豚ロース"],
    "toriniku":  ["鶏肉", "とりにく", "チキン", "chicken", "鶏もも", "鶏むね", "鶏ささみ", "手羽元", "手羽先"],
    "hikiniku":  ["ひき肉", "ひき肉", "挽肉", "合いびき肉", "ground meat"],
    "sake":      ["鮭", "サケ", "さけ", "salmon"],
    "saba":      ["さば", "サバ", "鯖", "mackerel"],
    "tara":      ["たら", "タラ", "鱈", "cod"],

    # 加工品・その他
    "tofu":      ["豆腐", "とうふ", "tofu", "絹ごし豆腐", "木綿豆腐"],
    "abura_age": ["油揚げ", "あぶらあげ", "アブラアゲ"],
    "konnyaku":  ["こんにゃく", "コンニャク", "蒟蒻"],
    "shiratake": ["しらたき", "シラタキ", "白滝"],
    "tamago":    ["卵", "たまご", "玉子", "egg"],
    "miso":      ["味噌", "みそ", "ミソ"],
    "shoyu":     ["醤油", "しょうゆ", "ショウユ", "soy sauce"],
    "gyunyu":    ["牛乳", "ぎゅうにゅう", "ミルク", "milk"],
    "kome":      ["米", "こめ", "rice", "白米"],
    "pasta":     ["パスタ", "ぱすた", "spaghetti", "スパゲッティ", "スパゲティ"],
    "ninniku":   ["にんにく", "ニンニク", "garlic"],
    "shouga":    ["しょうが", "ショウガ", "生姜", "ginger"],
}

# 逆引き: alias_normalized → tag
_REVERSE_INDEX: dict[str, str] | None = None


def _build_reverse_index() -> dict[str, str]:
    out: dict[str, str] = {}
    for tag, aliases in INGREDIENT_ALIASES.items():
        out[tag.lower()] = tag  # tag 自身も alias 扱い
        for alias in aliases:
            normalized = _normalize(alias)
            if normalized in out and out[normalized] != tag:
                logger.warning(
                    "duplicate alias '%s': %s vs %s", normalized, out[normalized], tag,
                )
            out[normalized] = tag
    return out


def _normalize(s: str) -> str:
    """全角→半角、カタカナ正規化、不要記号除去、lowercase。"""
    if not s:
        return ""
    # NFKC で全半角・カナ正規化
    s = unicodedata.normalize("NFKC", s)
    # かっこと中身を除去
    s = re.sub(r"[\(（].*?[\)）]", "", s)
    # 不要記号
    s = re.sub(r"[★☆◆◇■□●○\s]", "", s)
    return s.strip().lower()


@dataclass(frozen=True)
class ResolveResult:
    raw: str
    tag: str | None              # 確定したタグ。未解決なら None
    confidence: float            # 0.0〜1.0
    method: str                  # "exact" / "fuzzy" / "fallback"


def resolve(name: str, *, fuzzy_threshold: int = 88) -> ResolveResult:
    """1 食材を解決して ResolveResult を返す。

    Args:
      name: ユーザー入力 (例: "じゃがいも")
      fuzzy_threshold: rapidfuzz スコア閾値 (0〜100)。短い食材名は誤爆しやすいので高め
    """
    global _REVERSE_INDEX
    if _REVERSE_INDEX is None:
        _REVERSE_INDEX = _build_reverse_index()

    raw = name or ""
    normalized = _normalize(raw)
    if not normalized:
        return ResolveResult(raw=raw, tag=None, confidence=0.0, method="fallback")

    # 1) 完全一致
    if normalized in _REVERSE_INDEX:
        return ResolveResult(
            raw=raw, tag=_REVERSE_INDEX[normalized], confidence=1.0, method="exact"
        )

    # 2) 曖昧一致 (rapidfuzz)
    candidates = list(_REVERSE_INDEX.keys())
    match = fuzz_process.extractOne(normalized, candidates, score_cutoff=fuzzy_threshold)
    if match is not None:
        matched_alias, score, _ = match
        return ResolveResult(
            raw=raw,
            tag=_REVERSE_INDEX[matched_alias],
            confidence=round(score / 100.0, 2),
            method="fuzzy",
        )

    # 3) 解決失敗 — タグなしで返す
    return ResolveResult(raw=raw, tag=None, confidence=0.0, method="fallback")


def resolve_many(names: list[str]) -> list[ResolveResult]:
    return [resolve(n) for n in names]


def reset_for_tests() -> None:
    global _REVERSE_INDEX
    _REVERSE_INDEX = None
