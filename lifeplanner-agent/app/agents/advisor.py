"""Advisor エージェント — シナリオ結果を自然言語で要約・助言。

設計方針:
  - 数値計算は行わない (Simulator / ScenarioComparer の結果を受け取るのみ)
  - LLM の役割は「結果の自然言語化 + 一般的な節税・ライフプランの示唆」
  - 誤情報を避けるため、プロンプトで金額単位と事実ベースを明示
  - 免責文言を末尾に付ける
"""

from __future__ import annotations

import logging
from decimal import Decimal

from agents.simulator import SimulationResult
from services.llm_client import LLMClient
from services.scenario_comparer import ComparisonReport

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """あなたは日本の家計・ライフプランに精通したファイナンシャル・プランナーです。
渡される数値データは Python で決定論計算された結果です。あなた自身で再計算してはいけません。

ルール:
- 金額は全て「円」単位。日本の住宅・教育・税制・社会保障を前提。
- 投資助言ではなく、数値の客観的な読み解きと一般的な示唆に留める。
- 応答の末尾に次の免責を必ず記載: 「本シミュレーションは参考値であり、投資・税務助言ではありません。」
- 日本語で簡潔に。読み手は日本の共働き世帯を想定。
"""


def _format_yen(v: Decimal) -> str:
    """大きな金額を「1,234万円」「1.2億円」表記にする。"""
    n = int(v)
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 100_000_000:
        return f"{sign}{n / 100_000_000:.2f}億円"
    if n >= 10_000:
        return f"{sign}{n / 10_000:.0f}万円"
    return f"{sign}{n:,}円"


def _format_simulation_facts(scenario_name: str, result: SimulationResult) -> str:
    """単一シナリオの fact bullet。"""
    if not result.rows:
        return f"- シナリオ「{scenario_name}」: データなし"
    first = result.rows[0]
    last = result.rows[-1]
    min_row = min(result.rows, key=lambda r: r.net_worth_end)
    max_row = max(result.rows, key=lambda r: r.net_worth_end)
    lines = [
        f"- シナリオ名: {scenario_name}",
        f"- シミュレーション期間: {first.year}〜{last.year} ({len(result.rows)}年)",
        f"- 年末純資産の推移: 初年度 {_format_yen(first.net_worth_end)} / 最終年度 {_format_yen(last.net_worth_end)}",
        f"- 期間中の純資産レンジ: 最小 {_format_yen(min_row.net_worth_end)} ({min_row.year}年) / 最大 {_format_yen(max_row.net_worth_end)} ({max_row.year}年)",
        f"- 累計手取り: {_format_yen(result.total_take_home)}",
        f"- 累計税負担: {_format_yen(result.total_tax_paid)}",
        f"- 累計社会保険料: {_format_yen(result.total_social_insurance)}",
        f"- ライフイベント差分累計: {_format_yen(result.total_event_net)}",
    ]
    return "\n".join(lines)


def _format_comparison_facts(report: ComparisonReport) -> str:
    """複数シナリオ比較の fact bullet。"""
    lines = [
        "## ベースシナリオ",
        f"- 名称: {report.base.name}",
        f"- 最終年末純資産: {_format_yen(report.base.total_net_worth_end)}",
        f"- 純資産レンジ: 最小 {_format_yen(report.base.min_net_worth)} ({report.base.min_net_worth_year}年)"
        f" / 最大 {_format_yen(report.base.max_net_worth)} ({report.base.max_net_worth_year}年)",
        f"- 累計イベント差分: {_format_yen(report.base.total_event_net)}",
        "",
        "## 比較シナリオ",
    ]
    for cs, diff in zip(report.compares, report.diffs, strict=True):
        lines.append(f"### {cs.name}")
        lines.append(f"- 最終年末純資産: {_format_yen(cs.total_net_worth_end)}"
                     f" (ベースとの差 {_format_yen(diff.net_worth_diff)})")
        lines.append(f"- 累計手取り差: {_format_yen(diff.take_home_diff)}")
        lines.append(f"- 累計税負担差: {_format_yen(diff.tax_diff)}")
        lines.append(f"- 累計イベント差分差: {_format_yen(diff.event_net_diff)}")
        lines.append("")
    return "\n".join(lines)


async def narrate_simulation(
    *,
    client: LLMClient,
    scenario_name: str,
    result: SimulationResult,
    user_question: str | None = None,
) -> str:
    """単一シナリオのシミュレーション結果を自然言語で要約。"""
    facts = _format_simulation_facts(scenario_name, result)
    user_prompt = (
        "以下はシミュレーション結果です。事実に基づき 3〜5 段落で要約し、"
        "節目となる年と改善余地(節税・貯蓄・投資)を指摘してください。\n\n"
        f"{facts}\n"
    )
    if user_question:
        user_prompt += f"\n追加質問: {user_question}\n"
    return await client.complete(system=_SYSTEM_PROMPT, user=user_prompt)


async def narrate_comparison(
    *,
    client: LLMClient,
    report: ComparisonReport,
    user_question: str | None = None,
) -> str:
    """複数シナリオ比較を自然言語で要約。"""
    facts = _format_comparison_facts(report)
    user_prompt = (
        "以下は複数シナリオの比較結果です。ベースと各比較シナリオの差を読み解き、"
        "どのシナリオがどの局面で有利かを具体的な数値を引用しながら 4〜6 段落で説明してください。"
        "最後に意思決定の観点を箇条書きで示してください。\n\n"
        f"{facts}\n"
    )
    if user_question:
        user_prompt += f"\n追加質問: {user_question}\n"
    return await client.complete(system=_SYSTEM_PROMPT, user=user_prompt)
