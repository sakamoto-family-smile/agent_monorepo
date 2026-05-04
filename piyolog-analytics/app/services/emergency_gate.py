"""Phase 3: 緊急キーワード検出 (regex のみ、LLM は呼ばない)。

ユーザーが consulting mode で送ったテキストに対し、医療緊急性が高い表現を
検出して **Claude に渡す前** に #8000 / 119 案内を返すゲート。

設計判断:
- LLM 判定だと外す可能性があるので regex で雑に拾い、誤検知を許容する
- マッチしたら ALWAYS 救急案内を返す (Claude を呼ばない)
- 偽陽性は OK (例: 「元気だった」等は当たらない)、偽陰性は NG なので
  キーワードは多めに

Note: 本ゲートは医療判断の代替ではなく、危険そうな兆候を素早く救急/相談窓口に
誘導するための薄いセーフティネット。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

EMERGENCY_REPLY = (
    "🚨 緊急の可能性がある内容です。\n"
    "Bot による相談ではなく、以下にすぐご連絡ください:\n"
    "\n"
    "・救急の場合: 119\n"
    "・夜間・休日の小児救急電話相談: #8000\n"
    "・近くの夜間診療: お住まいの自治体ホームページ\n"
    "\n"
    "その後、必要であれば bot で記録の確認や相談も可能です。"
)

# regex は raw string で。一致しやすさ重視 (誤検知容認)。
# 数字 (39 度 / 40 度) は半角・全角両対応のため意図的に置換せず単純列挙。
_EMERGENCY_PATTERNS: list[str] = [
    r"高熱",
    r"40度",
    r"40\s*\.\s*\d",  # 40.x度
    r"39度",
    r"39\s*\.\s*\d",  # 39.x度
    r"ひきつけ",
    r"けいれん",
    r"痙攣",
    # 「呼吸が」「呼吸の」など助詞を間に挟むケースに対応
    r"呼吸\s*[がのは]?\s*(?:しない|苦しい|おかしい|止ま[るっ]た?)",
    r"息\s*[がのは]?\s*(?:できない|苦しい|止ま[るっ]た?)",
    r"意識\s*[がのは]?\s*(?:ない|朦朧|失[うっ]た?)",
    r"ぐったり",
    r"反応(?:がない|しない)",
    r"チアノーゼ",
    r"唇(?:が紫|が青)",
    r"大量出血",
    r"血が止まらない",
    r"頭(?:を打った|をぶつけた)",
    r"嘔吐(?:止まらない|が止まらない|緑色|血)",
    r"吐血",
    r"下血",
    r"自殺",  # 産後うつのスクリーニング兼用
    r"死にたい",
]

_EMERGENCY_RE = re.compile("|".join(_EMERGENCY_PATTERNS))


@dataclass(frozen=True)
class EmergencyMatch:
    """マッチしたキーワード (デバッグ・ログ用)。"""

    matched_text: str


def check(text: str) -> EmergencyMatch | None:
    """text に緊急キーワードを検出したら EmergencyMatch、なければ None。

    text は user の生発話そのまま (LINE message)。空 / None は非マッチ。
    """
    if not text:
        return None
    m = _EMERGENCY_RE.search(text)
    if m is None:
        return None
    return EmergencyMatch(matched_text=m.group(0))


__all__ = [
    "EMERGENCY_REPLY",
    "EmergencyMatch",
    "check",
]
