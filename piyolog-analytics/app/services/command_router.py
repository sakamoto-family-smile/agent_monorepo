"""テキストコマンドの解釈と応答生成 (Phase 1 + Phase 1.5)。

LINE でユーザが送るテキスト/コマンドを、対応する period query / chart /
help に振り分ける。未知のコマンドは「ヘルプを参照」のヒントで応答。

Phase 1.5: chart コマンドを追加。`CommandResult.image_png` が non-None なら
LINE 側で ImageMessage 送信する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from repositories.event_repo import EventRepo
from services import visualizer
from services.analytics import render_summary_text, resolve_period, summarize

JST = timezone(timedelta(hours=9), "Asia/Tokyo")


HELP_TEXT = (
    "【ぴよログ分析 Bot】\n"
    "■ 取り込み\n"
    "  ・ぴよログアプリからエクスポートした .txt を添付で送信\n"
    "  ・取り消し / undo — 直近の取り込みを取り消し\n"
    "\n"
    "■ サマリ (テキストコマンド)\n"
    "  ・今日 / today — 今日のサマリ\n"
    "  ・昨日 / yesterday — 昨日のサマリ\n"
    "  ・週間 / week — 直近 7 日\n"
    "  ・月間 / month — 今月\n"
    "  ・期間 2026-04-01 2026-04-15 — 指定期間\n"
    "\n"
    "■ グラフ (Phase 1.5)\n"
    "  ・ミルク / milk [週間|月間] — ミルク量グラフ\n"
    "  ・睡眠 / sleep [週間|月間] — 睡眠時間グラフ\n"
    "  ・体重 / weight — 体重・身長・頭囲の推移 (1 ヶ月)\n"
    "  ・時間帯 / heatmap — 授乳ヒートマップ (1 ヶ月)\n"
    "  ・ダッシュボード / dashboard — 4 種を 1 枚に集約\n"
    "  ※ 期間指定: 例 ミルク 期間 2026-02-01 2026-02-28\n"
    "\n"
    "■ 設定 (Phase 4-B)\n"
    "  ・⚙️ 設定 ボタン — 子の生年月日 / 名前を登録\n"
    "  ・名前: たろう — 子の名前を直接設定\n"
    "\n"
    "■ その他\n"
    "  ・ヘルプ / help — このメッセージ\n"
    "\n"
    "※ 夫婦の別端末から同じ family として集計されます。"
)

UNKNOWN_HINT = "認識できない入力でした。「ヘルプ」と送るとコマンド一覧を表示します。"

INVALID_PERIOD_HINT = (
    "期間指定は「期間 YYYY-MM-DD YYYY-MM-DD」の形式で送ってください。\n"
    "例: 期間 2026-04-01 2026-04-15"
)

CHART_NO_DATA_HINT = "対象期間にデータがありません。.txt を添付で送って取り込んでください。"


# コマンド別名
_HELP_TOKENS = frozenset({"ヘルプ", "help", "menu", "メニュー", "?", "？"})
_TODAY_TOKENS = frozenset({"今日", "today"})
_YESTERDAY_TOKENS = frozenset({"昨日", "yesterday"})
_WEEK_TOKENS = frozenset({"週間", "week"})
_MONTH_TOKENS = frozenset({"月間", "month"})
_PERIOD_TOKENS = frozenset({"期間", "period"})

# Phase 1.5 chart コマンド
_MILK_TOKENS = frozenset({"ミルク", "milk"})
_SLEEP_TOKENS = frozenset({"睡眠", "sleep"})
_WEIGHT_TOKENS = frozenset({"体重", "weight"})
_HEATMAP_TOKENS = frozenset({"時間帯", "heatmap", "ヒートマップ"})
_DASHBOARD_TOKENS = frozenset({"ダッシュボード", "dashboard"})

# Phase 1.5 ロールバック
_UNDO_TOKENS = frozenset({"取り消し", "取消", "undo", "rollback"})

# Phase 3 consulting mode 切替 (line_handler 側で intercept される)
CONSULT_ENTER_TOKENS = frozenset({"相談", "consult", "相談開始"})
CONSULT_EXIT_TOKENS = frozenset({"相談終了", "exit", "終了"})

UNDO_NO_BATCH_HINT = (
    "取り消せる取り込み履歴がありません。\n"
    "( .txt の取り込みが 1 件もないか、既にすべて取り消し済みです)"
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class CommandResult:
    """コマンド実行結果。

    reply: テキスト応答 (画像送信時は alt 兼キャプション)
    image_png: 画像本体 (PNG bytes)。None ならテキストのみ
    chart_kind: 画像種別 (ログ・metrics 用、optional)
    quick_reply: テキスト応答に付ける Quick Reply ボタン (Phase 4-B 設定 UI 用)
    """

    reply: str
    image_png: bytes | None = None
    chart_kind: str | None = None
    quick_reply: tuple = ()  # tuple[QuickReplyAction, ...] (frozen friendly)


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

    if cmd in _UNDO_TOKENS or cmd_lower in _UNDO_TOKENS:
        return await _handle_undo(repo=repo, family_id=family_id)

    chart_result = await _try_chart_command(
        cmd, cmd_lower, args, repo=repo, family_id=family_id, now=now
    )
    if chart_result is not None:
        return chart_result

    return CommandResult(reply=UNKNOWN_HINT)


async def _handle_undo(*, repo: EventRepo, family_id: str) -> CommandResult:
    """直近の取り込みバッチを論理削除。

    `EventRepo.rollback_latest_batch` の戻り値で確認メッセージを生成する。
    対象なしなら UNDO_NO_BATCH_HINT を返す (fail-safe)。
    """
    batch = await repo.rollback_latest_batch(family_id=family_id)
    if batch is None:
        return CommandResult(reply=UNDO_NO_BATCH_HINT)
    filename = batch.source_filename or "(no name)"
    imported_at_short = batch.imported_at[:19].replace("T", " ")
    msg = (
        "🔄 直近の取り込みを取り消しました。\n"
        f"ファイル: {filename}\n"
        f"取り込み日時: {imported_at_short} UTC\n"
        f"件数: {batch.event_count} 件\n"
        "この同じ .txt は再度送信して取り込み直すことができます。"
    )
    return CommandResult(reply=msg)


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


async def _try_chart_command(
    cmd: str,
    cmd_lower: str,
    args: list[str],
    *,
    repo: EventRepo,
    family_id: str,
    now: datetime | None,
) -> CommandResult | None:
    """chart コマンドにマッチしたら CommandResult を返す。マッチしなければ None。"""
    chart_kind: str | None = None
    default_period = "week"
    if cmd in _MILK_TOKENS or cmd_lower in _MILK_TOKENS:
        chart_kind = "milk"
    elif cmd in _SLEEP_TOKENS or cmd_lower in _SLEEP_TOKENS:
        chart_kind = "sleep"
    elif cmd in _WEIGHT_TOKENS or cmd_lower in _WEIGHT_TOKENS:
        chart_kind = "weight"
        default_period = "month"
    elif cmd in _HEATMAP_TOKENS or cmd_lower in _HEATMAP_TOKENS:
        chart_kind = "heatmap"
        default_period = "month"
    elif cmd in _DASHBOARD_TOKENS or cmd_lower in _DASHBOARD_TOKENS:
        chart_kind = "dashboard"

    if chart_kind is None:
        return None

    # ---- 引数解析 ----
    # サポート形式:
    #   <chart>                              → default_period
    #   <chart> 今日 / 週間 / 月間 ...      → preset period override
    #   <chart> 期間 YYYY-MM-DD YYYY-MM-DD  → 任意期間 (summary と同 syntax)
    is_period_keyword = bool(args) and (
        args[0] in _PERIOD_TOKENS or args[0].lower() in _PERIOD_TOKENS
    )
    if is_period_keyword:
        if len(args) < 3 or not _DATE_RE.match(args[1]) or not _DATE_RE.match(args[2]):
            return CommandResult(reply=INVALID_PERIOD_HINT)
        try:
            date_from, date_to, label = resolve_period(
                "period", now=now, custom_from=args[1], custom_to=args[2]
            )
        except ValueError:
            return CommandResult(reply=INVALID_PERIOD_HINT)
    else:
        requested_period = default_period
        if args:
            candidate = args[0].lower()
            period_resolved = _match_period(args[0], candidate)
            if period_resolved is not None:
                requested_period = period_resolved
        date_from, date_to, label = resolve_period(requested_period, now=now)

    return await render_chart(
        chart_kind=chart_kind,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        label=label,
        repo=repo,
        family_id=family_id,
    )


CHART_KINDS = ("milk", "sleep", "weight", "heatmap", "dashboard")


async def render_chart(
    *,
    chart_kind: str,
    date_from: str,
    date_to: str,
    label: str,
    repo: EventRepo,
    family_id: str,
) -> CommandResult:
    """指定の chart_kind と期間 (ISO date 文字列) で events 取得 → 画像生成。

    text コマンド (handle_text_command 経由) と Postback Router の両方から
    呼び出される共通エントリポイント。

    chart_kind は CHART_KINDS のいずれか。範囲内に events が無ければ
    CHART_NO_DATA_HINT のテキスト reply を返す。
    """
    if chart_kind not in CHART_KINDS:
        return CommandResult(reply=UNKNOWN_HINT)
    events = await repo.fetch_events_in_range(
        family_id=family_id, date_from=date_from, date_to=date_to
    )
    if not events:
        return CommandResult(reply=CHART_NO_DATA_HINT)

    if chart_kind == "milk":
        png = visualizer.milk_timeline(events, period=label)
    elif chart_kind == "sleep":
        png = visualizer.sleep_timeline(events, period=label)
    elif chart_kind == "weight":
        png = visualizer.weight_height_timeline(events, period=label)
    elif chart_kind == "heatmap":
        png = visualizer.feeding_heatmap(events, period=label)
    else:  # dashboard
        png = visualizer.dashboard(events, period=label)

    return CommandResult(
        reply=f"📊 {chart_kind} ({label})",
        image_png=png,
        chart_kind=chart_kind,
    )


async def render_summary(
    *,
    period: str,
    repo: EventRepo,
    family_id: str,
    now: datetime | None = None,
    custom_from: str | None = None,
    custom_to: str | None = None,
) -> CommandResult:
    """Postback / text command 共通の summary エントリポイント。"""
    s = await summarize(
        repo=repo,
        family_id=family_id,
        period=period,
        now=now,
        custom_from=custom_from,
        custom_to=custom_to,
    )
    return CommandResult(reply=render_summary_text(s))
