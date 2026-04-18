"""Advisor エージェント (narrate_simulation / narrate_comparison) のテスト。

LLM は MockLLMClient で差し替える。プロンプトに事実(金額)が正しく含まれているかを検証。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from agents.advisor import (
    _format_comparison_facts,
    _format_simulation_facts,
    _format_yen,
    narrate_comparison,
    narrate_simulation,
)
from agents.event_catalog import BirthEventParams, expand_birth_event
from agents.simulator import (
    HouseholdProfile,
    SimulationAssumptions,
    run_projection,
)
from services.llm_client import MockLLMClient
from services.scenario_comparer import compare_scenarios


class CapturingMockClient:
    """MockLLMClient の拡張: 最後のプロンプトを保持する。"""

    def __init__(self, reply: str = "MOCK") -> None:
        self._reply = reply
        self.last_system: str | None = None
        self.last_user: str | None = None

    async def complete(self, *, system: str, user: str) -> str:
        self.last_system = system
        self.last_user = user
        return self._reply


def _build_result():
    profile = HouseholdProfile(
        primary_salary=Decimal(6_000_000),
        spouse_salary=Decimal(3_000_000),
        base_annual_expense=Decimal(4_200_000),
        initial_net_worth=Decimal(5_000_000),
    )
    assumptions = SimulationAssumptions(start_year=2026, horizon_years=30)
    return run_projection(profile, assumptions)


# --- 単位フォーマット --------------------------------------------------------


def test_format_yen_small_amount():
    assert _format_yen(Decimal(9999)) == "9,999円"


def test_format_yen_man_scale():
    # 10,000 円は万の境界
    assert _format_yen(Decimal(10_000)) == "1万円"
    assert _format_yen(Decimal(1_500_000)) == "150万円"


def test_format_yen_oku_scale():
    assert _format_yen(Decimal(150_000_000)) == "1.50億円"


def test_format_yen_negative():
    assert _format_yen(Decimal(-5_000_000)) == "-500万円"


# --- Facts フォーマット -----------------------------------------------------


def test_simulation_facts_contains_key_numbers():
    result = _build_result()
    facts = _format_simulation_facts("Baseline", result)
    assert "Baseline" in facts
    assert "2026" in facts
    assert "2055" in facts
    # 年末純資産が含まれる
    assert "最終年度" in facts
    assert "累計手取り" in facts
    assert "累計税負担" in facts


def test_comparison_facts_contains_base_and_compares():
    base = _build_result()
    alt = run_projection(
        HouseholdProfile(
            primary_salary=Decimal(6_000_000),
            spouse_salary=Decimal(3_000_000),
            base_annual_expense=Decimal(4_200_000),
            initial_net_worth=Decimal(5_000_000),
        ),
        SimulationAssumptions(start_year=2026, horizon_years=30),
        expand_birth_event(
            BirthEventParams(
                birth_year=2027,
                parental_leave_parent_salary=Decimal(4_800_000),
                household_income_for_childcare=Decimal(9_000_000),
            ),
            horizon_years=30,
        ),
    )
    report = compare_scenarios(
        base=(1, "Baseline", base),
        compares=[(2, "With Child", alt)],
    )
    facts = _format_comparison_facts(report)
    assert "Baseline" in facts
    assert "With Child" in facts
    assert "ベースとの差" in facts


# --- Narrate 経由で LLM にプロンプトを流す ----------------------------------


@pytest.mark.asyncio
async def test_narrate_simulation_uses_system_prompt_and_includes_facts():
    client = CapturingMockClient(reply="要約テキスト")
    result = _build_result()
    out = await narrate_simulation(
        client=client, scenario_name="Baseline", result=result
    )
    assert out == "要約テキスト"
    assert client.last_system is not None
    assert "ファイナンシャル" in client.last_system
    assert "Baseline" in (client.last_user or "")
    assert "免責" in (client.last_system or "")


@pytest.mark.asyncio
async def test_narrate_simulation_with_user_question_includes_it():
    client = CapturingMockClient()
    result = _build_result()
    await narrate_simulation(
        client=client,
        scenario_name="Baseline",
        result=result,
        user_question="60歳時点の資産推移は？",
    )
    assert "60歳" in (client.last_user or "")


@pytest.mark.asyncio
async def test_narrate_comparison_passes_diffs_in_prompt():
    base = _build_result()
    alt = run_projection(
        HouseholdProfile(
            primary_salary=Decimal(6_000_000),
            spouse_salary=Decimal(3_000_000),
            base_annual_expense=Decimal(4_200_000),
            initial_net_worth=Decimal(5_000_000),
        ),
        SimulationAssumptions(start_year=2026, horizon_years=30),
        expand_birth_event(BirthEventParams(birth_year=2027), horizon_years=30),
    )
    report = compare_scenarios(
        base=(1, "Baseline", base), compares=[(2, "With Child", alt)]
    )
    client = CapturingMockClient(reply="比較要約")
    out = await narrate_comparison(client=client, report=report)
    assert out == "比較要約"
    assert "比較シナリオ" in (client.last_user or "")
    assert "With Child" in (client.last_user or "")


@pytest.mark.asyncio
async def test_mock_client_works_without_override():
    """MockLLMClient 既定モードでも narrate が返す(決定論)。"""
    result = _build_result()
    mock = MockLLMClient()
    out = await narrate_simulation(client=mock, scenario_name="X", result=result)
    assert "モック" in out
