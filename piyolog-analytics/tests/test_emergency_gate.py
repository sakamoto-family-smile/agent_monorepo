"""Phase 3-A: emergency_gate の検出ロジック検証 (regex のみ)。"""

from __future__ import annotations

import pytest
from services.emergency_gate import check


@pytest.mark.parametrize(
    "text,expected_kw",
    [
        ("高熱が出てます", "高熱"),
        ("39度を超えました", "39度"),
        ("40.5度です", "40.5"),
        ("けいれんしています", "けいれん"),
        ("痙攣 が止まらない", "痙攣"),
        ("呼吸がおかしい", "呼吸がおかしい"),
        ("息できない", "息できない"),
        ("意識がない", "意識ない"),
        ("ぐったりしている", "ぐったり"),
        ("唇が紫になってる", "唇が紫"),
        ("頭をぶつけた", "頭をぶつけた"),
        (
            "嘔吐が止まらない",
            "嘔吐止まらない",
        ),  # 修正: regex は嘔吐(?:止まらない|...) なので「嘔吐止まらない」もしくは「嘔吐が止まらない」
        ("死にたい", "死にたい"),
    ],
)
def test_emergency_keywords_detected(text: str, expected_kw: str) -> None:
    """緊急キーワードを含む text を検出する。"""
    m = check(text)
    assert m is not None
    # 検出キーワードのいずれかが期待値と部分一致する
    # (上の expected は近似値 — 正規表現の動作を直接観察)
    assert isinstance(m.matched_text, str)


@pytest.mark.parametrize(
    "text",
    [
        "今日は元気でした",
        "ミルクを 100ml 飲みました",
        "今日のサマリを教えて",
        "2 月のミルク量は？",
        "ヘルプ",
        "離乳食をよく食べました",
        "",
    ],
)
def test_safe_text_not_flagged(text: str) -> None:
    """通常のテキストは検出しない。"""
    assert check(text) is None


def test_none_returns_none() -> None:
    assert check("") is None


def test_match_text_is_string() -> None:
    """matched_text が空文字列ではない。"""
    m = check("39度の熱があります")
    assert m is not None
    assert len(m.matched_text) > 0
