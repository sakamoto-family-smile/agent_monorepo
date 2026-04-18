"""LifePlannerOrchestrator — 自然言語質問をシミュツール呼び出しに結び付ける薄い層。

Phase 3a スコープ:
  - 質問意図分類: 「単一シナリオ要約」か「複数シナリオ比較」か
  - 明示されたシナリオ ID を抽出 (ID リストが無ければエラー)
  - 決定論ツール (simulate_scenario / compare_scenarios) を呼び出し、
    Advisor に narrative を依頼

分類は LLM ではなく単純なヒューリスティック (まずはルールベース)。
将来的に LLM ベースの function calling へ拡張する想定。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from agents.advisor import narrate_comparison, narrate_simulation
from repositories.scenario import get_scenario_for_household
from services.llm_client import LLMClient
from services.scenario_comparer import compare_scenarios
from services.scenario_runner import simulate_scenario
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    SUMMARIZE = "summarize"       # 単一シナリオの要約
    COMPARE = "compare"           # 複数シナリオの比較
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ChatResult:
    intent: Intent
    narrative: str
    scenario_ids: list[int]


def classify_intent(scenario_ids: list[int]) -> Intent:
    """scenario_ids の数で単純分類。

    - 0 件: UNKNOWN (ルート側で 400 を返す想定)
    - 1 件: SUMMARIZE
    - 2 件以上: COMPARE
    """
    if not scenario_ids:
        return Intent.UNKNOWN
    if len(scenario_ids) == 1:
        return Intent.SUMMARIZE
    return Intent.COMPARE


async def run_chat(
    *,
    session: AsyncSession,
    household_id: str,
    scenario_ids: list[int],
    question: str | None,
    llm: LLMClient,
) -> ChatResult:
    """指定シナリオに対する自然言語質問を処理する。

    Raises:
      ValueError: いずれかの scenario_id がユーザーの世帯に見つからない
    """
    intent = classify_intent(scenario_ids)
    if intent is Intent.UNKNOWN:
        raise ValueError("At least one scenario_id is required")

    # シナリオ取得 + シミュ実行 (既存結果を捨てて再計算する方が安全)
    loaded: list[tuple[int, str, object]] = []
    for sid in scenario_ids:
        scenario = await get_scenario_for_household(session, sid, household_id)
        if scenario is None:
            raise ValueError(f"Scenario not found: {sid}")
        result = await simulate_scenario(session, scenario)
        loaded.append((scenario.id, scenario.name, result))

    if intent is Intent.SUMMARIZE:
        sid, name, result = loaded[0]
        narrative = await narrate_simulation(
            client=llm,
            scenario_name=name,
            result=result,  # type: ignore[arg-type]
            user_question=question,
        )
        return ChatResult(intent=intent, narrative=narrative, scenario_ids=[sid])

    # COMPARE
    base_id, base_name, base_result = loaded[0]
    compares = loaded[1:]
    report = compare_scenarios(
        base=(base_id, base_name, base_result),  # type: ignore[arg-type]
        compares=[(c[0], c[1], c[2]) for c in compares],  # type: ignore[arg-type]
    )
    narrative = await narrate_comparison(
        client=llm, report=report, user_question=question
    )
    return ChatResult(
        intent=intent,
        narrative=narrative,
        scenario_ids=[x[0] for x in loaded],
    )
