"""レッスン計測テキストの取り込み (§3.1.2・§4.2.1)。

- 計測モードで貼ったテキスト、またはボタンなしでも計測の書式のテキストを読み取って保存する
- 入れ先のセッションは計測の日時で決め、返事に出す。違えば「付け替え」で選び直せる
- 検算に引っかかった球があれば確認待ちにし、「確定」か「取消」を選んでもらう
- 計測モードで 1 球も読めなければ、捨てずに「メモとして保存しますか？」と聞く
"""
from __future__ import annotations

import json
from collections import Counter

import sqlalchemy as sa

from app.handlers.common import Context, Messages, with_status
from app.lesson.checks import check
from app.lesson.parser import ParseResult, Shot, parse
from app.line.api import postback_item, text
from app.storage import entries, lessons, modes, sessions
from app.storage.modes import Mode
from app.storage.tables import raw_events

MAX_FLAG_LINES = 5
MAX_REASSIGN_CHOICES = 6


def _summary(shots: list[Shot]) -> str:
    if len(shots) == 1:
        shot = shots[0]
        parts = []
        if "carry_yd" in shot.values:
            parts.append(f"キャリー {shot.values['carry_yd']:g}yd")
        offline = shot.values.get("offline_yd")
        if offline is not None:
            side = "左" if offline < 0 else "右" if offline > 0 else ""
            parts.append(f"{side} {abs(offline):g}yd".strip())
        detail = f"（{' / '.join(parts)}）" if parts else ""
        return f"⛳ {shot.club or shot.club_label or 'クラブ不明'} 1 球を保存{detail}"
    clubs = Counter(s.club or "不明" for s in shots)
    return f"⛳ {len(shots)} 球を保存（{'・'.join(f'{c}×{n}' for c, n in clubs.items())}）"


def _capture_items(capture_id: int, pending: bool) -> list[dict]:
    items = []
    if pending:
        items += [
            postback_item("確定", f"action=capture&id={capture_id}&status=confirmed", "確定"),
            postback_item("取消", f"action=capture&id={capture_id}&status=rejected", "取消"),
        ]
    return [*items, postback_item("付け替え", f"action=reassign&capture={capture_id}", "セッションを付け替え")]


async def handle_text(ctx: Context, body: str, mode: Mode, *, auto: bool) -> Messages | None:
    """保存したら返事を返す。読めなかった場合は計測モードなら質問を返し、自動判定なら None (メモにする)。"""
    result: ParseResult = parse(body, ctx.deps.settings.tz)
    if not result.shots:
        if auto:
            return None
        await modes.extend(ctx.conn, ctx.user_id, ctx.now)
        return [
            text(
                "📊 計測として読み取れませんでした。メモとして保存しますか？",
                quick_reply=[postback_item("メモとして保存", f"action=memo_from&raw={ctx.raw_event_id}", "メモとして保存")],
            )
        ]

    session = await sessions.session_for_shot(
        ctx.conn, result.shots[0].shot_at, ctx.now, ctx.deps.settings.tz
    )
    flags = [check(shot) for shot in result.shots]
    capture = await lessons.save_text_capture(
        ctx.conn,
        session_id=session.id,
        raw_event_id=ctx.raw_event_id,
        raw_text=body,
        shots=result.shots,
        flags=flags,
        now=ctx.now,
    )
    if mode.name == "metrics":
        await modes.extend(ctx.conn, ctx.user_id, ctx.now)

    lines = [with_status(_summary(result.shots), session, mode if mode.name == "metrics" else None)]
    if auto:
        lines.append("計測として保存しました（違えば「取消」）。")
    if result.unreadable:
        numbers = ", ".join(str(n) for n, _ in result.unreadable[:10])
        lines.append(f"読めなかった行: {numbers} 行目（原文は残しています）")
    flagged = [(shot, f) for shot, f in zip(result.shots, flags, strict=True) if f]
    for shot, shot_flags in flagged[:MAX_FLAG_LINES]:
        lines.append(f"⚠️ {shot.shot_no} 球目 {shot.club or ''}: {'／'.join(f.message for f in shot_flags)}")
    if flagged:
        lines.append("確かめて「確定」か「取消」を選んでください。")
    return [text("\n".join(lines), quick_reply=_capture_items(capture.id, capture.status == "pending"))]


def _int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


async def confirm(ctx: Context, data: dict[str, str]) -> Messages:
    capture_id, status = _int(data.get("id")), data.get("status")
    if capture_id is None or status not in lessons.STATUSES:
        return []
    if not await lessons.set_status(ctx.conn, capture_id, status):
        return []
    word = "確定しました" if status == "confirmed" else "取り消しました（分析には使いません）"
    return [text(f"📊 計測 #{capture_id} を{word}。")]


async def reassign(ctx: Context, data: dict[str, str]) -> Messages:
    capture_id = _int(data.get("capture"))
    capture = await lessons.get(ctx.conn, capture_id) if capture_id else None
    if capture is None:
        return []
    choices = await sessions.recent(ctx.conn, MAX_REASSIGN_CHOICES, exclude=capture.session_id)
    if not choices:
        return [text("付け替え先のセッションがありません。")]
    return [
        text(
            f"📊 計測 #{capture.id} をどのセッションに入れますか？",
            quick_reply=[
                postback_item(s.label, f"action=reassign_to&capture={capture.id}&session={s.id}", s.label)
                for s in choices
            ],
        )
    ]


async def reassign_to(ctx: Context, data: dict[str, str]) -> Messages:
    capture_id, session_id = _int(data.get("capture")), _int(data.get("session"))
    if capture_id is None or session_id is None:
        return []
    session = await sessions.get(ctx.conn, session_id)
    if session is None or not await lessons.move(ctx.conn, capture_id, session_id):
        return []
    return [text(f"📊 計測 #{capture_id} を{session.label}に入れました。")]


async def memo_from(ctx: Context, data: dict[str, str]) -> Messages:
    """計測として読めなかったテキストを、あとからメモとして保存する。"""
    raw_id = _int(data.get("raw"))
    if raw_id is None:
        return []
    row = (
        await ctx.conn.execute(
            sa.select(raw_events.c.payload_json, raw_events.c.user_id, raw_events.c.message_type).where(
                raw_events.c.id == raw_id
            )
        )
    ).first()
    if row is None or row.user_id != ctx.user_id or row.message_type != "text":
        return []
    body = (json.loads(row.payload_json).get("message") or {}).get("text", "").strip()
    if not body or await entries.memo_exists(ctx.conn, raw_id):
        return []
    session = await sessions.session_for_item(ctx.conn, ctx.now, ctx.deps.settings.tz)
    await entries.add_memo(ctx.conn, session_id=session.id, raw_event_id=raw_id, text=body, now=ctx.now)
    return [text(with_status("📝 メモとして保存しました", session))]
