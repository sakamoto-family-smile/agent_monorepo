"""総合判断の読み取り (PROPOSAL-0014)。"""

from __future__ import annotations

import pytest
from agents.verdict import Verdict, parse_verdict


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("本文\n総合判断: 強気 / 確信度: 高", Verdict("bullish", "high")),
        ("総合判断：中立／確信度：中", Verdict("neutral", "medium")),
        ("**総合判断: 弱気** / **確信度: 低**", Verdict("bearish", "low")),
        ("総合判断: **強気** | 確信度: **中**", Verdict("bullish", "medium")),
    ],
)
def test_reads_verdict_line(text, expected):
    assert parse_verdict(text) == expected


def test_last_occurrence_wins():
    text = "例: 総合判断: 弱気 / 確信度: 低 のように書く\n...\n総合判断: 強気 / 確信度: 中"
    assert parse_verdict(text) == Verdict("bullish", "medium")


@pytest.mark.parametrize("text", ["", "総合評価は強気です", "総合判断: やや強気 / 確信度: 高", None])
def test_returns_none_when_missing(text):
    assert parse_verdict(text) is None
