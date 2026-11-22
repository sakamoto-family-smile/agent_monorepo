"""分析結果から採点用の値を取り出す (PROPOSAL-0014)。"""

from __future__ import annotations

from agents import orchestrator
from agents.forecast import ForecastResult


def _forecast() -> ForecastResult:
    return ForecastResult(
        horizon_days=2,
        percentiles=(10, 50, 90),
        bands={10: (95.0, 90.0), 50: (100.0, 101.0), 90: (105.0, 112.0)},
        dates=("2026-11-24", "2026-11-25"),
        last_price=100.0,
        last_date="2026-11-21",
    )


def test_takes_final_day_bands_and_verdict():
    ev = orchestrator._build_evaluation("本文\n総合判断: 弱気 / 確信度: 高", _forecast(), "t" * 32)
    assert (ev.stance, ev.confidence, ev.trace_id) == ("bearish", "high", "t" * 32)
    assert (ev.base_date, ev.base_close) == ("2026-11-21", 100.0)
    assert (ev.forecast_horizon_days, ev.forecast_end_date) == (2, "2026-11-25")
    assert ev.forecast_bands == {10: 90.0, 50: 101.0, 90: 112.0}


def test_without_forecast_or_verdict_keeps_trace_only():
    ev = orchestrator._build_evaluation("総合評価は強気", None, "t" * 32)
    assert ev.trace_id == "t" * 32
    assert ev.stance is None and ev.forecast_bands is None and ev.base_close is None
