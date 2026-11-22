"""リッチメニュー・Quick Reply のボタン (postback) の処理 (§4.3.1)。

data は ``action=<名前>&...`` の形。自分で作ったボタンから届くが、値はすべて許可した値か数値かを確かめる。
"""
from __future__ import annotations

from urllib.parse import parse_qsl

from app.handlers.common import (
    ANGLES,
    CLUBS,
    NO_CLUB,
    Context,
    Messages,
    angle_items,
    club_items,
    video_label,
    with_status,
)
from app.line.api import postback_item, text
from app.storage import courses, entries, modes, sessions
from app.storage.sessions import KIND_LABELS

PURPOSES = {"metrics": "計測画像", "other": "その他の画像"}
MAX_RECENT_COURSES = 10


def _int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


async def handle(ctx: Context) -> Messages:
    data = dict(parse_qsl(ctx.ev.postback_data or "", max_num_fields=10))
    action = data.get("action")
    handler = HANDLERS.get(action or "")
    return await handler(ctx, data) if handler else []


async def _mode(ctx: Context, data: dict[str, str]) -> Messages:
    name = data.get("mode")
    if name == "memo":
        await modes.clear(ctx.conn, ctx.user_id)
        session = await sessions.open_session(ctx.conn, ctx.now)
        return [text(with_status("📝 メモモードです。テキストはメモとして保存します", session))]
    if name == "metrics":
        return [text("📊 計測テキストの読み取りは次の更新で対応します。いまはメモとして保存されます。")]
    if name == "video":
        return [text("🎥 アングルは？", quick_reply=angle_items("action=video_angle"))]
    if name == "score":
        mode = await modes.set_mode(ctx.conn, ctx.user_id, "score", ctx.now)
        session = await sessions.open_session(ctx.conn, ctx.now)
        return [
            text(
                with_status("🏌 スコアを送ってください（例: 92 パット34 FW7/14 パーオン5。30 分有効）", session, mode)
            )
        ]
    if name == "ask":
        return [text("🔍 振り返りは準備中です。")]
    return []


async def _video_angle(ctx: Context, data: dict[str, str]) -> Messages:
    angle = data.get("angle")
    if angle not in ANGLES:
        return []
    await modes.set_mode(ctx.conn, ctx.user_id, "video", ctx.now, {"angle": angle})
    return [text(f"🎥 {ANGLES[angle]}。クラブは？", quick_reply=club_items(f"action=video_club&angle={angle}"))]


async def _video_club(ctx: Context, data: dict[str, str]) -> Messages:
    angle, club = data.get("angle"), data.get("club")
    if angle not in ANGLES or (club not in CLUBS and club != NO_CLUB):
        return []
    params = {"angle": angle, "club": None if club == NO_CLUB else club}
    mode = await modes.set_mode(ctx.conn, ctx.user_id, "video", ctx.now, params)
    session = await sessions.open_session(ctx.conn, ctx.now)
    body = f"🎥 動画を送ってください（{video_label(params)}。続けて送った動画も同じ設定で保存。30 分有効）"
    return [text(with_status(body, session, mode))]


async def _tag(ctx: Context, data: dict[str, str]) -> Messages:
    """モードなしで送った動画・画像に、あとからアングル・クラブ・用途を付ける。"""
    media_id = _int(data.get("media"))
    if media_id is None:
        return []
    angle, club, purpose = data.get("angle"), data.get("club"), data.get("purpose")
    if angle in ANGLES:
        if not await entries.tag_media(ctx.conn, media_id, "video", angle=angle):
            return []
        return [
            text(f"🎥 #{media_id} を{ANGLES[angle]}にしました。クラブは？", quick_reply=club_items(f"action=tag&media={media_id}"))
        ]
    if club in CLUBS or club == NO_CLUB:
        if not await entries.tag_media(ctx.conn, media_id, "video", club=None if club == NO_CLUB else club):
            return []
        return [text(f"🎥 #{media_id} のクラブを{club if club != NO_CLUB else '指定なし'}にしました。")]
    if purpose in PURPOSES:
        if not await entries.tag_media(ctx.conn, media_id, "image", purpose=purpose):
            return []
        return [text(f"🖼 #{media_id} を{PURPOSES[purpose]}にしました。")]
    return []


async def _session(ctx: Context, _data: dict[str, str]) -> Messages:
    current = await sessions.open_session(ctx.conn, ctx.now)
    if current:
        return [
            text(
                f"▶ {current.label}中です。終了しますか？",
                quick_reply=[
                    postback_item("終了する", "action=session_end", "終了"),
                    postback_item("続ける", "action=noop", "続ける"),
                ],
            )
        ]
    return [
        text(
            "▶ 何を始めますか？",
            quick_reply=[
                postback_item(label, f"action=session_start&kind={kind}", f"{label}を開始")
                for kind, label in KIND_LABELS.items()
            ],
        )
    ]


async def _session_start(ctx: Context, data: dict[str, str]) -> Messages:
    kind = data.get("kind")
    if kind not in KIND_LABELS:
        return []
    session = await sessions.start(ctx.conn, kind, ctx.now, ctx.deps.settings.tz)
    if kind != "round":
        await modes.clear(ctx.conn, ctx.user_id)
        return [text(with_status(f"▶ {KIND_LABELS[kind]}を開始しました", session))]
    mode = await modes.set_mode(ctx.conn, ctx.user_id, "course", ctx.now, {"session_id": session.id})
    recent = await courses.recent(ctx.conn, MAX_RECENT_COURSES)
    items = [
        postback_item(c.name, f"action=course&session={session.id}&course={c.id}", c.name) for c in recent
    ]
    return [
        text(
            with_status("▶ ラウンドを開始しました。コース名を送ってください（最近のコースは下から選べます）", session, mode),
            quick_reply=items or None,
        )
    ]


async def _course(ctx: Context, data: dict[str, str]) -> Messages:
    session_id, course_id = _int(data.get("session")), _int(data.get("course"))
    if session_id is None or course_id is None:
        return []
    session = await sessions.get(ctx.conn, session_id)
    course = await courses.get(ctx.conn, course_id)
    if session is None or course is None:
        return []
    await sessions.set_course(ctx.conn, session.id, course.id)
    await modes.clear(ctx.conn, ctx.user_id)
    return [text(with_status(f"⛳ コースを「{course.name}」にしました", session))]


async def end_session(ctx: Context, _data: dict[str, str] | None = None) -> Messages:
    await modes.clear(ctx.conn, ctx.user_id)
    current = await sessions.open_session(ctx.conn, ctx.now)
    if current is None:
        return [text("⏹ 入力モードを解除しました（開いているセッションはありません）。")]
    await sessions.end(ctx.conn, current.id, ctx.now)
    n = await entries.counts(ctx.conn, current.id)
    return [
        text(
            f"⏹ {current.label}を終了しました（メモ {n['memo']}・動画/画像 {n['media']}・スコア {n['score']}）。"
        )
    ]


async def _noop(_ctx: Context, _data: dict[str, str]) -> Messages:
    return []


HANDLERS = {
    "mode": _mode,
    "video_angle": _video_angle,
    "video_club": _video_club,
    "tag": _tag,
    "session": _session,
    "session_start": _session_start,
    "session_end": end_session,
    "course": _course,
    "noop": _noop,
}
