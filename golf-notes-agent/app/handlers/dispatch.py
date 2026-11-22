"""届いたイベントを保存し、reply で返すメッセージを決める。

webhook の中で DB に書き終えてから返事を作る (返事に書いたことが保存済みであるように)。
あとで動く処理 (動画・画像の取得) はジョブに積み、結果が失敗のときだけ push で知らせる。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from app.deps import Deps
from app.jobs import media as media_job
from app.jobs import queue
from app.line.api import text
from app.line.events import LineEvent
from app.storage import entries, sessions
from app.storage.sessions import SessionRef

UNDO_WORDS = frozenset({"取消", "取り消し", "とりけし"})
MEDIA_TYPES = {"image": "画像", "video": "動画"}


@dataclass(frozen=True)
class Context:
    deps: Deps
    conn: AsyncConnection
    ev: LineEvent
    raw_event_id: int
    now: datetime


def with_status(body: str, session: SessionRef | None) -> str:
    return f"{body} ｜ {session.label}" if session else body


async def handle(ctx: Context) -> list[dict[str, Any]]:
    ev = ctx.ev
    if ev.type != "message":
        return []
    if ev.message_type == "text":
        return await _text(ctx, (ev.text or "").strip())
    if ev.message_type in MEDIA_TYPES:
        return await _media(ctx)
    return [text("このメッセージの種類は保存の対象外です（届いた記録は残しています）。")]


async def _text(ctx: Context, body: str) -> list[dict[str, Any]]:
    if body in UNDO_WORDS:
        return await _undo(ctx)
    if not body:
        return []
    session = await sessions.session_for_item(ctx.conn, ctx.now, ctx.deps.settings.tz)
    await entries.add_memo(
        ctx.conn, session_id=session.id, raw_event_id=ctx.raw_event_id, text=body, now=ctx.now
    )
    return [text(with_status("📝 メモを保存しました", session))]


async def _media(ctx: Context) -> list[dict[str, Any]]:
    ev = ctx.ev
    session = await sessions.session_for_item(ctx.conn, ctx.now, ctx.deps.settings.tz)
    media_id = await entries.add_media(
        ctx.conn,
        session_id=session.id,
        raw_event_id=ctx.raw_event_id,
        kind=ev.message_type or "",
        now=ctx.now,
        duration_ms=ev.duration_ms,
    )
    await queue.enqueue(ctx.conn, media_job.KIND, media_id, ctx.now)
    label = MEDIA_TYPES[ev.message_type or ""]
    icon = "🎥" if ev.message_type == "video" else "🖼"
    return [text(with_status(f"{icon} {label}を受け付けました（保存に失敗したときだけお知らせします）", session))]


async def _undo(ctx: Context) -> list[dict[str, Any]]:
    assert ctx.ev.user_id is not None
    entry = await entries.latest(ctx.conn, ctx.ev.user_id)
    if entry is None:
        return [text("取り消せるものがありません。")]
    await entries.undo(ctx.conn, entry, ctx.now)
    return [text(f"↩️ 直前の{entry.label}を取り消しました（#{entry.id}）。")]
