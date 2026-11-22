"""届いたメッセージを保存し、reply で返すメッセージを決める (§4.3.1)。

webhook の中で DB に書き終えてから返事を作る (返事に書いたことが保存済みであるように)。
あとで動く処理 (動画・画像の取得) はジョブに積み、結果が失敗のときだけ push で知らせる。

いまの入力モードで扱いを変える:
  メモ (既定)  テキストはメモ。動画・画像は保存してから、アングル・クラブ / 計測画像かどうかを聞く
  動画モード   動画を選んだアングル・クラブ付きで保存する (テキストはメモ)
  計測モード   テキストを計測として読み取る (ボタンなしでも計測の書式なら計測として保存する)
  スコアモード テキストをスコアの原文として保存する
  コース名     ラウンド開始の直後。テキストをそのラウンドのコース名にする
"""
from __future__ import annotations

from app.handlers import lesson, postback
from app.handlers.common import Context, Messages, angle_items, video_label, with_status
from app.jobs import media as media_job
from app.jobs import queue
from app.lesson.parser import looks_like_metrics
from app.line.api import postback_item, text
from app.storage import courses, entries, modes, sessions
from app.storage.modes import Mode

UNDO_WORDS = frozenset({"取消", "取り消し", "とりけし"})
END_WORDS = frozenset({"終了", "おわり"})
ASK_PREFIXES = ("?", "？")
MEDIA_TYPES = {"image": "画像", "video": "動画"}


async def handle(ctx: Context) -> Messages:
    ev = ctx.ev
    if ev.type == "postback":
        return await postback.handle(ctx)
    if ev.type != "message":
        return []
    mode = await modes.current(ctx.conn, ctx.user_id, ctx.now)
    if ev.message_type == "text":
        return await _text(ctx, (ev.text or "").strip(), mode)
    if ev.message_type in MEDIA_TYPES:
        return await _media(ctx, mode)
    return [text("このメッセージの種類は保存の対象外です（届いた記録は残しています）。")]


async def _text(ctx: Context, body: str, mode: Mode) -> Messages:
    if not body:
        return []
    if body in UNDO_WORDS:
        return await _undo(ctx)
    if body in END_WORDS:
        return await postback.end_session(ctx)
    if body.startswith(ASK_PREFIXES):
        return [text("🔍 振り返りは準備中です（送った質問は記録しています）。")]
    if mode.name == "course":
        return await _course(ctx, body, mode)
    if mode.name == "metrics":
        return await lesson.handle_text(ctx, body, mode, auto=False) or []
    if mode.name != "score" and looks_like_metrics(body):
        saved = await lesson.handle_text(ctx, body, mode, auto=True)
        if saved is not None:
            return saved

    session = await sessions.session_for_item(ctx.conn, ctx.now, ctx.deps.settings.tz)
    if mode.name == "score":
        await entries.add_score(
            ctx.conn, session_id=session.id, raw_event_id=ctx.raw_event_id, text=body, now=ctx.now
        )
        await modes.extend(ctx.conn, ctx.user_id, ctx.now)
        return [text(with_status("🏌 スコアを保存しました（集計は今後の更新で行います）", session, mode))]

    await entries.add_memo(
        ctx.conn, session_id=session.id, raw_event_id=ctx.raw_event_id, text=body, now=ctx.now
    )
    if mode.name != modes.MEMO:
        await modes.extend(ctx.conn, ctx.user_id, ctx.now)
    return [text(with_status("📝 メモを保存しました", session, mode))]


async def _course(ctx: Context, body: str, mode: Mode) -> Messages:
    session_id = int(mode.params.get("session_id", 0))
    session = await sessions.get(ctx.conn, session_id)
    await modes.clear(ctx.conn, ctx.user_id)
    if session is None:
        return [text("ラウンドが見つかりませんでした。もう一度「開始」からやり直してください。")]
    course = await courses.find_or_create(ctx.conn, body)
    await sessions.set_course(ctx.conn, session.id, course.id)
    return [text(with_status(f"⛳ コースを「{course.name}」にしました", session))]


async def _media(ctx: Context, mode: Mode) -> Messages:
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

    if ev.message_type == "video":
        if mode.name == "video":
            await entries.tag_media(
                ctx.conn, media_id, "video", angle=mode.params.get("angle"), club=mode.params.get("club")
            )
            await modes.extend(ctx.conn, ctx.user_id, ctx.now)
            label = video_label(mode.params)
            body = f"🎥 動画を受け付けました（{label}）" if label else "🎥 動画を受け付けました"
            return [text(with_status(body, session, mode))]
        return [
            text(
                with_status(f"🎥 動画を受け付けました（#{media_id}）。アングルは？", session, mode),
                quick_reply=angle_items(f"action=tag&media={media_id}"),
            )
        ]

    if mode.name == "metrics":
        await entries.tag_media(ctx.conn, media_id, "image", purpose="metrics")
        await modes.extend(ctx.conn, ctx.user_id, ctx.now)
        return [text(with_status("🖼 計測画像を受け付けました（画像の読み取りは Phase 2 で行います）", session, mode))]
    prefix = f"action=tag&media={media_id}"
    return [
        text(
            with_status(f"🖼 画像を受け付けました（#{media_id}）。計測結果の画像ですか？", session, mode),
            quick_reply=[
                postback_item("計測画像", f"{prefix}&purpose=metrics", "計測画像"),
                postback_item("その他", f"{prefix}&purpose=other", "その他の画像"),
            ],
        )
    ]


async def _undo(ctx: Context) -> Messages:
    entry = await entries.latest(ctx.conn, ctx.user_id)
    if entry is None:
        return [text("取り消せるものがありません。")]
    await entries.undo(ctx.conn, entry, ctx.now)
    return [text(f"↩️ 直前の{entry.label}を取り消しました（#{entry.id}）。")]
