"""The analysis prompt must carry forecast numbers from the simulation (never let
the LLM invent them) and a clear non-advice disclaimer."""

import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


def _forecast():
    from agents.forecast import MonteCarloForecaster
    from models.stock import OHLCVData

    base = date(2024, 1, 2)
    ohlcv = []
    price = 1000.0
    import random
    rng = random.Random(3)
    for i in range(120):
        price *= 1 + rng.gauss(0.0005, 0.012)
        ohlcv.append(OHLCVData(
            date=str(base + timedelta(days=i)),
            open=price, high=price * 1.01, low=price * 0.99, close=price, volume=1,
        ))
    return MonteCarloForecaster(n_paths=500, seed=9).forecast(ohlcv, horizon_days=21)


def test_format_forecast_summary_contains_band_values_and_disclaimer():
    from agents.orchestrator import _format_forecast_summary

    fc = _forecast()
    text = _format_forecast_summary(fc)

    assert "21" in text  # horizon
    # median end value should appear, formatted to 2 decimals like the impl
    assert f"{fc.bands[50][-1]:.2f}" in text
    assert "投資助言" in text or "投資判断" in text  # disclaimer present


def test_format_forecast_summary_handles_none():
    from agents.orchestrator import _format_forecast_summary

    assert _format_forecast_summary(None) == ""


def test_prompt_includes_forecast_block_when_present():
    from agents.orchestrator import _build_analysis_prompt

    fc = _forecast()
    prompt = _build_analysis_prompt(
        ticker="TEST.T",
        company_name="テスト",
        ohlcv_summary="x",
        technical_summary="y",
        fundamental_summary="z",
        forecast_summary="<<FORECAST_BLOCK>>",
    )
    assert "<<FORECAST_BLOCK>>" in prompt
    # instruction telling the model not to fabricate numbers
    assert "予測" in prompt


def test_forecast_instruction_numbered_after_edinet():
    from agents.orchestrator import _build_analysis_prompt

    # EDINET off -> forecast item is 6
    p_no_edinet = _build_analysis_prompt(
        ticker="T", company_name="c", ohlcv_summary="x",
        technical_summary="y", fundamental_summary="z",
        forecast_summary="FB",
    )
    assert "6. **価格予測の解説**" in p_no_edinet
    # EDINET on -> forecast item is 7
    p_edinet = _build_analysis_prompt(
        ticker="T", company_name="c", ohlcv_summary="x",
        technical_summary="y", fundamental_summary="z",
        edinet_section="some edinet data",
        forecast_summary="FB",
    )
    assert "7. **価格予測の解説**" in p_edinet


def test_prompt_omits_forecast_block_when_absent():
    from agents.orchestrator import _build_analysis_prompt

    prompt = _build_analysis_prompt(
        ticker="TEST.T",
        company_name="テスト",
        ohlcv_summary="x",
        technical_summary="y",
        fundamental_summary="z",
    )
    assert "FORECAST_BLOCK" not in prompt
