"""レポート末尾の総合判断を読み取る (PROPOSAL-0014)。

プロンプトで最後の行を「総合判断: 強気 / 確信度: 高」の形にさせ、ここで読み取って保存する。
読み取れなければ None (分析は止めない)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VERDICT_INSTRUCTION = (
    "レポートの最後の行には、次の形式で総合判断を 1 行だけ書いてください: "
    "「総合判断: 強気 / 確信度: 高」 (判断は 強気・中立・弱気、確信度は 高・中・低 から 1 つずつ選ぶ)"
)

_STANCES = {"強気": "bullish", "中立": "neutral", "弱気": "bearish"}
_CONFIDENCES = {"高": "high", "中": "medium", "低": "low"}

# Markdown の強調 (** や __) や全角の記号が混ざっても読めるようにする
_PATTERN = re.compile(
    r"総合判断\s*[:：]\s*[*_]*\s*(強気|中立|弱気)\s*[*_]*\s*[/／|｜、,]\s*[*_]*\s*"
    r"確信度\s*[:：]\s*[*_]*\s*(高|中|低)"
)


@dataclass(frozen=True)
class Verdict:
    stance: str  # bullish / neutral / bearish
    confidence: str  # high / medium / low


def parse_verdict(text: str) -> Verdict | None:
    """最後に現れた総合判断を返す (本文中の例示より末尾の行を優先する)。"""
    matches = _PATTERN.findall(text or "")
    if not matches:
        return None
    stance, confidence = matches[-1]
    return Verdict(_STANCES[stance], _CONFIDENCES[confidence])
