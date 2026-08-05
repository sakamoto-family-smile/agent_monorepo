"""投資判断 (購入推奨) セクションのテスト。

レポート末尾に固定書式の「## 投資判断」セクションを LLM に出力させ、
orchestrator がそれを構造化 (`BuyRecommendation`) してレポート・LINE Flex に
反映する (案B)。推奨的な出力には免責文を必ず付ける方針 (投信ランキング・
モンテカルロ予測と同様) を踏襲する。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


# ---------------------------------------------------------------------------
# プロンプト: 投資判断の指示
# ---------------------------------------------------------------------------


def _build_prompt(**kwargs):
    from agents.orchestrator import _build_analysis_prompt

    defaults = dict(
        ticker="TEST.T",
        company_name="テスト",
        ohlcv_summary="x",
        technical_summary="y",
        fundamental_summary="z",
    )
    defaults.update(kwargs)
    return _build_analysis_prompt(**defaults)


def test_prompt_includes_recommendation_instruction_with_fixed_format():
    prompt = _build_prompt()
    assert "投資判断" in prompt
    # 固定書式 (パース対象) の 3 択が明示されている
    assert "買い検討" in prompt
    assert "様子見" in prompt
    assert "見送り" in prompt
    # 見出し書式の指示
    assert "## 投資判断" in prompt


def test_prompt_recommendation_includes_disclaimer():
    from models.stock import BUY_RECOMMENDATION_DISCLAIMER

    prompt = _build_prompt()
    assert BUY_RECOMMENDATION_DISCLAIMER in prompt


def test_recommendation_item_is_numbered_last():
    # base のみ → 6
    assert "6. **投資判断**" in _build_prompt()
    # EDINET あり → 7
    assert "7. **投資判断**" in _build_prompt(edinet_section="e")
    # 予測あり → 7
    assert "7. **投資判断**" in _build_prompt(forecast_summary="f")
    # 両方 → 8
    assert "8. **投資判断**" in _build_prompt(edinet_section="e", forecast_summary="f")


# ---------------------------------------------------------------------------
# パーサ: report_text → BuyRecommendation
# ---------------------------------------------------------------------------


_REPORT_BUY = """# テスト分析

## テクニカル分析
上昇トレンド。

## 投資判断
判定: 買い検討
根拠:
- RSI 55 で過熱感なく上昇トレンド継続
- PER 12倍と割安
反対シナリオ:
- 決算下振れで急落する場合

※ 本判定は情報提供のみを目的としています。
"""

_REPORT_HOLD = """## 投資判断
判定: 様子見
根拠:
- 方向感に乏しい
"""

_REPORT_AVOID = """## 投資判断
判定: 見送り
根拠:
- 下落トレンドが継続
"""


def test_parse_buy_candidate():
    from agents.orchestrator import _parse_buy_recommendation

    reco = _parse_buy_recommendation(_REPORT_BUY)
    assert reco is not None
    assert reco.rating == "buy_candidate"
    assert reco.label == "買い検討"


def test_parse_hold_and_avoid():
    from agents.orchestrator import _parse_buy_recommendation

    assert _parse_buy_recommendation(_REPORT_HOLD).rating == "hold"
    assert _parse_buy_recommendation(_REPORT_AVOID).rating == "avoid"


def test_parse_extracts_reasons():
    from agents.orchestrator import _parse_buy_recommendation

    reco = _parse_buy_recommendation(_REPORT_BUY)
    assert len(reco.reasons) == 2
    assert "RSI 55" in reco.reasons[0]
    # 反対シナリオの bullet は根拠に混ぜない
    assert all("急落" not in r for r in reco.reasons)


def test_parse_sets_disclaimer():
    from agents.orchestrator import _parse_buy_recommendation
    from models.stock import BUY_RECOMMENDATION_DISCLAIMER

    reco = _parse_buy_recommendation(_REPORT_BUY)
    assert reco.disclaimer == BUY_RECOMMENDATION_DISCLAIMER


def test_parse_missing_section_returns_none():
    from agents.orchestrator import _parse_buy_recommendation

    assert _parse_buy_recommendation("# 分析\n総合評価: 中立") is None
    assert _parse_buy_recommendation("") is None


def test_parse_unknown_verdict_returns_none():
    from agents.orchestrator import _parse_buy_recommendation

    assert _parse_buy_recommendation("## 投資判断\n判定: わからない\n") is None
    assert _parse_buy_recommendation("## 投資判断\n根拠:\n- 判定行なし\n") is None


def test_parse_verdict_with_trailing_note():
    from agents.orchestrator import _parse_buy_recommendation

    reco = _parse_buy_recommendation("## 投資判断\n判定: 様子見（買い材料不足）\n")
    assert reco is not None
    assert reco.rating == "hold"


# ---------------------------------------------------------------------------
# モデル: AnalysisReport への組み込み
# ---------------------------------------------------------------------------


def test_analysis_report_serializes_recommendation():
    from datetime import datetime

    from models.stock import AnalysisReport, BuyRecommendation

    report = AnalysisReport(
        ticker="7203.T",
        generated_at=datetime(2026, 8, 5),
        recommendation=BuyRecommendation(
            rating="buy_candidate", label="買い検討", reasons=["割安"]
        ),
    )
    dumped = report.model_dump(mode="json")
    assert dumped["recommendation"]["rating"] == "buy_candidate"
    assert "投資" in dumped["recommendation"]["disclaimer"]

    # 既定は None (後方互換)
    assert (
        AnalysisReport(ticker="X", generated_at=datetime(2026, 8, 5)).recommendation
        is None
    )


# ---------------------------------------------------------------------------
# LINE Flex: 判定バッジ
# ---------------------------------------------------------------------------


def _bubble_texts(bubble: dict) -> str:
    return str(bubble)


def test_bubble_shows_badge_and_disclaimer():
    from services.line_flex import analysis_summary_bubble

    bubble = analysis_summary_bubble(
        ticker="7203.T",
        company_name="トヨタ",
        body_text="本文",
        recommendation={
            "rating": "buy_candidate",
            "label": "買い検討",
            "reasons": ["割安", "上昇トレンド"],
            "disclaimer": "※ 投資判断は自己責任で。",
        },
    )
    texts = _bubble_texts(bubble)
    assert "買い検討" in texts
    assert "🟢" in texts
    assert "自己責任" in texts  # 免責文も表示


def test_bubble_badge_colors_by_rating():
    from services.line_flex import analysis_summary_bubble

    def _badge(rating: str, label: str) -> str:
        b = analysis_summary_bubble(
            ticker="X",
            company_name=None,
            body_text="t",
            recommendation={"rating": rating, "label": label},
        )
        return _bubble_texts(b)

    assert "🟢" in _badge("buy_candidate", "買い検討")
    assert "🟡" in _badge("hold", "様子見")
    assert "🔴" in _badge("avoid", "見送り")


def test_bubble_without_recommendation_has_no_badge():
    from services.line_flex import analysis_summary_bubble

    bubble = analysis_summary_bubble(
        ticker="X", company_name=None, body_text="本文のみ"
    )
    texts = _bubble_texts(bubble)
    assert "🟢" not in texts and "🟡" not in texts and "🔴" not in texts


def test_bubble_unknown_rating_is_ignored():
    from services.line_flex import analysis_summary_bubble

    bubble = analysis_summary_bubble(
        ticker="X",
        company_name=None,
        body_text="t",
        recommendation={"rating": "unknown", "label": "?"},
    )
    assert "🟢" not in _bubble_texts(bubble)
