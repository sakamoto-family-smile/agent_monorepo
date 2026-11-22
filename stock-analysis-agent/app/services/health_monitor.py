"""ローカル常駐時の死活監視 (PROPOSAL-0013 §5.1)。

security-platform の `src/notify/health.py` と同じく「最後に成功した時刻が古すぎないか」を見る。
状態が変わったとき (異常になった / 戻った) だけ管理者の LINE に知らせる。
Mac 自体の停止は内側からは分からないので、Healthchecks.io への ping (scheduler) と併用する。

監視項目:
- edinet:index  EDINET index の定期実行の最終成功が STALE_AFTER より古い
- backup        最新の backup ファイルが STALE_AFTER より古い
- funnel        PUBLIC_BASE_URL 経由で /api/line/webhook に届かない (外から LINE が届くかの確認)
- analysis      分析が ANALYSIS_FAILURE_THRESHOLD 回続けて失敗している
- llm-gateway   LLM gateway (LiteLLM) が応答しない (PROPOSAL-0014。止まると分析がすべて失敗する)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx

import config
from services.backup import list_backups

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(hours=26)  # 日次ジョブ 1 回分の遅れまでは許す
ANALYSIS_FAILURE_THRESHOLD = 3
FUNNEL_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Check:
    key: str
    ok: bool
    detail: str


def _age_detail(now: datetime, last: datetime | None) -> str:
    if last is None:
        return "成功の記録なし"
    hours = (now - last).total_seconds() / 3600
    return f"最終成功 {hours:.0f} 時間前"


def freshness_check(key: str, now: datetime, last: datetime | None) -> Check:
    ok = last is not None and now - last <= STALE_AFTER
    return Check(key, ok, _age_detail(now, last))


def backup_check(now: datetime, backup_dir: Path) -> Check:
    backups = list_backups(backup_dir)
    return freshness_check("backup", now, backups[-1][0] if backups else None)


def analysis_check(consecutive_failures: int) -> Check:
    ok = consecutive_failures < ANALYSIS_FAILURE_THRESHOLD
    return Check("analysis", ok, f"連続失敗 {consecutive_failures} 回")


async def funnel_check(public_base_url: str, client: httpx.AsyncClient) -> Check:
    """公開 URL から webhook まで届くか。GET には backend が 405 を返すので、405 なら届いている。"""
    url = f"{public_base_url}/api/line/webhook"
    try:
        resp = await client.get(url, timeout=FUNNEL_TIMEOUT_SECONDS)
    except httpx.HTTPError as e:
        return Check("funnel", False, f"接続できません ({type(e).__name__})")
    if resp.status_code == 405:
        return Check("funnel", True, "到達可能")
    return Check("funnel", False, f"想定外の応答 HTTP {resp.status_code}")


async def gateway_check(gateway_url: str, client: httpx.AsyncClient) -> Check:
    """LiteLLM の liveliness は認証なしで 200 を返す。"""
    try:
        resp = await client.get(f"{gateway_url}/health/liveliness", timeout=FUNNEL_TIMEOUT_SECONDS)
    except httpx.HTTPError as e:
        return Check("llm-gateway", False, f"接続できません ({type(e).__name__})")
    if resp.status_code == 200:
        return Check("llm-gateway", True, "応答あり")
    return Check("llm-gateway", False, f"想定外の応答 HTTP {resp.status_code}")


async def collect_checks(
    *,
    now: datetime,
    last_success: Callable[[str], datetime | None],
    consecutive_failures: int,
    client: httpx.AsyncClient,
) -> list[Check]:
    s = config.settings
    checks = []
    if s.edinet_schedule_enabled:
        checks.append(freshness_check("edinet:index", now, last_success("edinet_index")))
    if s.backup_enabled:
        checks.append(backup_check(now, Path(s.backup_dir)))
    if s.public_base_url:
        checks.append(await funnel_check(s.public_base_url, client))
    if s.llm_gateway_url:
        checks.append(await gateway_check(s.llm_gateway_url, client))
    checks.append(analysis_check(consecutive_failures))
    return checks


def transitions(previous: dict[str, bool], checks: list[Check]) -> tuple[list[Check], list[Check]]:
    """(新たに異常になった項目, 復旧した項目)。初回 (previous に無い項目) は異常のときだけ数える。"""
    failed, recovered = [], []
    for c in checks:
        before = previous.get(c.key)
        if not c.ok and before is not False:
            failed.append(c)
        elif c.ok and before is False:
            recovered.append(c)
    return failed, recovered


def format_notice(failed: list[Check], recovered: list[Check]) -> str:
    lines = []
    if failed:
        lines.append("⚠️ stock-analysis-agent の監視で異常を検知しました")
        lines += [f"・{c.key}: {c.detail}" for c in failed]
    if recovered:
        if lines:
            lines.append("")
        lines.append("✅ 復旧しました")
        lines += [f"・{c.key}: {c.detail}" for c in recovered]
    return "\n".join(lines)


class HealthMonitor:
    """前回の状態を覚えておき、変化があったときだけ notify する。"""

    def __init__(self, notify: Callable[[str], Awaitable[None]]) -> None:
        self._notify = notify
        self._previous: dict[str, bool] = {}

    async def observe(self, checks: list[Check]) -> None:
        failed, recovered = transitions(self._previous, checks)
        self._previous = {c.key: c.ok for c in checks}
        if not failed and not recovered:
            return
        try:
            await self._notify(format_notice(failed, recovered))
        except Exception:
            logger.exception("failed to send health notice")


__all__ = [
    "Check",
    "HealthMonitor",
    "analysis_check",
    "backup_check",
    "collect_checks",
    "format_notice",
    "freshness_check",
    "funnel_check",
    "gateway_check",
    "transitions",
]
