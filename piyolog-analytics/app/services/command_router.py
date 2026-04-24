"""テキストコマンドの解釈と応答生成 (Phase 1)。

LINE でユーザが送るテキスト/コマンドを、対応する period query または help に振り分ける。
未知のコマンドは「ヘルプを参照」のヒントで応答。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from repositories.event_repo import EventRepo
from services.analytics import render_summary_text, summarize

JST = timezone(timedelta(hours=9), "Asia/Tokyo")


HELP_TEXT = (
    "【ぴよログ分析 Bot】\n"
    "■ 取り込み\n"
    "  ・ぴよログアプリからエクスポートした .txt を添付で送信\n"
    "\n"
    "■ サマリ (テキストコマンド)\n"
    "  ・今日 / today — 今日のサマリ\n"
    "  ・昨日 / yesterday — 昨日のサマリ\n"
    "  ・週間 / week — 直近 7 日\n"
    "  ・月間 / month — 今月\n"
    "  ・期間 2026-04-01 2026-04-15 — 指定期間\n"
    "\n"
    "■ その他\n"
    "  ・ヘルプ / help — このメッセージ\n"
    "\n"
    "※ 夫婦の別端末から同じ family として集計されます。"
)

UNKNOWN_HINT = (
    "認識できない入力でした。「ヘルプ」と送るとコマンド一覧を表示します。"
)

INVALID_PERIOD_HINT = (
    "期間指定は「期間 YYYY-MM-DD YYYY-MM-DD」の形式で送ってください。\n"
    "例: 期間 2026-04-01 2026-04-15"
)


# コマンド別名
_HELP_TOKENS = frozenset({"ヘルプ", "help", "menu", "メニュー", "?", "？"})
_TODAY_TOKENS = frozenset({"今日", "today"})
_YESTERDAY_TOKENS = frozenset({"昨日", "yesterday"})
_WEEK_TOKENS = frozenset({"週間", "week"})
_MONTH_TOKENS = frozenset({"月間", "month"})
_PERIOD_TOKENS = frozenset({"期間", "period"})

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class CommandResult:
    """コマンド実行結果。

    reply: テキスト応答 (必須)
    """

    reply: str


def _normalize(raw: str) -> tuple[str, list[str]]:
    s = raw.replace("\u3000", " ").strip()
    if s.startswith("/"):
        s = s[1:]
    parts = s.split()
    if not parts:
        return "", []
    return parts[0], parts[1:]


async def handle_text_command(
    text: str,
    *,
    repo: EventRepo,
    family_id: str,
    now: datetime | None = None,
) -> CommandResult:
    cmd, args = _normalize(text)
    if not cmd:
        return CommandResult(reply=UNKNOWN_HINT)

    cmd_lower = cmd.lower()

    if cmd in _HELP_TOKENS or cmd_lower in _HELP_TOKENS:
        return CommandResult(reply=HELP_TEXT)

    period = _match_period(cmd, cmd_lower)
    if period is not None:
        s = await summarize(repo=repo, family_id=family_id, period=period, now=now)
        return CommandResult(reply=render_summary_text(s))

    if cmd in _PERIOD_TOKENS or cmd_lower in _PERIOD_TOKENS:
        if len(args) < 2 or not _DATE_RE.match(args[0]) or not _DATE_RE.match(args[1]):
            return CommandResult(reply=INVALID_PERIOD_HINT)
        try:
            s = await summarize(
                repo=repo,
                family_id=family_id,
                period="period",
                now=now,
                custom_from=args[0],
                custom_to=args[1],
            )
        except ValueError:
            return CommandResult(reply=INVALID_PERIOD_HINT)
        return CommandResult(reply=render_summary_text(s))

    return CommandResult(reply=UNKNOWN_HINT)


def _match_period(cmd: str, cmd_lower: str) -> str | None:
    if cmd in _TODAY_TOKENS or cmd_lower in _TODAY_TOKENS:
        return "today"
    if cmd in _YESTERDAY_TOKENS or cmd_lower in _YESTERDAY_TOKENS:
        return "yesterday"
    if cmd in _WEEK_TOKENS or cmd_lower in _WEEK_TOKENS:
        return "week"
    if cmd in _MONTH_TOKENS or cmd_lower in _MONTH_TOKENS:
        return "month"
    return None
