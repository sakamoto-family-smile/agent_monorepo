"""LINE イベントをディスパッチし、コマンド / ファイル取り込みに振り分ける。

- TextMessage → command_router → reply_text
- FileMessage → ack reply → background job で取り込み → push_text で完了通知
  (取り込みは解析・INSERT 含めて数百 ms〜数秒で終わる想定だが、
   LINE の 3 秒制約を安全に守るため非同期化)
- access control: FAMILY_USER_IDS 外は応答しない
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from repositories.event_repo import EventRepo
from repositories.session_repo import (
    MODE_CONSULTING,
    MODE_NORMAL,
    SessionRepo,
)
from services.command_router import (
    CONSULT_ENTER_TOKENS,
    CONSULT_EXIT_TOKENS,
    handle_text_command,
)
from services.consultation import Consultation
from services.emergency_gate import EMERGENCY_REPLY
from services.emergency_gate import check as emergency_check
from services.image_store import ImageStore
from services.import_service import (
    DuplicateImportError,
    ImportOutcome,
    InvalidPiyologFileError,
    import_piyolog_bytes,
)
from services.line_client import (
    LineBotClient,
    LineEvent,
    LineFileEvent,
    LineFollowEvent,
    LinePostbackEvent,
    LineTextEvent,
)
from services.postback_router import handle_postback

logger = logging.getLogger(__name__)


@dataclass
class HandlerDeps:
    line_client: LineBotClient
    repo: EventRepo
    family_id: str
    family_user_ids: frozenset[str]
    default_child_id: str
    upload_max_bytes: int
    schedule_background: Callable[[Callable[[], Awaitable[None]]], None]
    # Phase 1.5: グラフ画像の一時保管 + 公開 URL 構築
    public_base_url: str = ""
    image_store: ImageStore | None = None
    # Phase 3: consultation 用の依存。session_repo + analytics_logger 必須。
    # rich_menu_id_consulting が空なら mode 切替時の rich menu link/unlink は skip。
    session_repo: SessionRepo | None = None
    analytics_logger: object | None = None
    rich_menu_id_consulting: str = ""
    # Optional: テストで時刻を固定したい場合に注入
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC)


async def handle_event(event: LineEvent, deps: HandlerDeps) -> None:
    # bootstrap mode: 許可リスト未設定なら、開通用に **完全な userId** を WARN ログに出す。
    # FAMILY_USER_IDS=Uxxx,Uyyy をデプロイ env に設定したら通常モードに戻る。
    # (運用中に許可リストを空にすると意図せず userId が漏れるリスクはあるが、
    #  許可リスト空状態はそもそも誰のメッセージにも応答しない open-webhook なので、
    #  本番運用でこの状態になることは想定しない。初回セットアップでだけ通る経路。)
    if not deps.family_user_ids:
        logger.warning(
            "[bootstrap] FAMILY_USER_IDS unset; received event from line_user_id=%s. "
            "Add this id to FAMILY_USER_IDS and redeploy to enable normal handling.",
            event.line_user_id,
        )
        return

    # access control
    if event.line_user_id not in deps.family_user_ids:
        logger.warning(
            "ignored event from non-family user: user_id_suffix=%s", event.line_user_id[-6:]
        )
        return

    if isinstance(event, LineTextEvent):
        await _handle_text(event, deps)
    elif isinstance(event, LineFileEvent):
        await _handle_file(event, deps)
    elif isinstance(event, LinePostbackEvent):
        await _handle_postback(event, deps)
    elif isinstance(event, LineFollowEvent):
        await _handle_follow(event, deps)
    else:
        logger.warning("unsupported event type: %r", event)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


async def _handle_text(event: LineTextEvent, deps: HandlerDeps) -> None:
    """text の振り分け。

    優先順:
      1. consulting mode 切替コマンド (相談 / 相談終了) を intercept
      2. consulting mode → emergency_gate → Consultation.respond
      3. normal mode → command_router (chart / summary / undo / help)
    """
    text_norm = (event.text or "").strip().replace("\u3000", " ")
    # 1. consulting mode 切替を最優先
    if (text_norm in CONSULT_ENTER_TOKENS) or (text_norm.lower() in CONSULT_ENTER_TOKENS):
        await _enter_consulting(event, deps)
        return
    if (text_norm in CONSULT_EXIT_TOKENS) or (text_norm.lower() in CONSULT_EXIT_TOKENS):
        await _exit_consulting(event, deps)
        return

    # 2. consulting mode 中なら Consultation に流す
    if deps.session_repo is not None:
        mode = await deps.session_repo.get_mode(line_user_id=event.line_user_id)
        if mode == MODE_CONSULTING:
            await _handle_consulting_text(event, deps)
            return

    # 3. normal mode: 既存 command_router
    result = await handle_text_command(
        event.text,
        repo=deps.repo,
        family_id=deps.family_id,
        now=deps.now_factory(),
    )
    if result.image_png is not None:
        await _send_image_or_fallback(event, deps, result)
        return
    await deps.line_client.reply_text(reply_token=event.reply_token, text=result.reply)


async def _handle_consulting_text(event: LineTextEvent, deps: HandlerDeps) -> None:
    """consulting mode のテキスト → emergency_gate → Consultation。"""
    # 緊急ワードがあれば LLM を呼ばずに #8000 / 119 案内
    if emergency_check(event.text or ""):
        await deps.line_client.reply_text(reply_token=event.reply_token, text=EMERGENCY_REPLY)
        return
    if deps.session_repo is None or deps.analytics_logger is None:
        # 設計上 None になることは想定外、防御的に normal にフォールバック
        logger.warning("session_repo / analytics_logger missing in consulting mode")
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text="相談機能の設定が不完全です。しばらくしてからもう一度お試しください。",
        )
        return
    consultant = Consultation(
        repo=deps.repo,
        session_repo=deps.session_repo,
        analytics_logger=deps.analytics_logger,
        family_id=deps.family_id,
        line_user_id=event.line_user_id,
    )
    reply = await consultant.respond(event.text or "")
    await deps.line_client.reply_text(reply_token=event.reply_token, text=reply)


CONSULT_ENTER_REPLY = (
    "💬 相談モードに入りました。\n"
    "ぴよログのデータをもとに、自然言語で質問できます。例:\n"
    "・2 月と 3 月のミルク量を比較して\n"
    "・直近 1 週間で寝つきが悪い日はいつ？\n"
    "・離乳食の頻度どう？\n"
    "\n"
    "終わるときは「相談終了」または 🚪 ボタンをタップしてください。\n"
    "緊急の症状 (高熱・けいれん等) は #8000 / 119 へ。"
)

CONSULT_EXIT_REPLY = "✅ 相談モードを終了しました。\n通常メニューに戻ります。"


async def _enter_consulting(event: LineTextEvent | LinePostbackEvent, deps: HandlerDeps) -> None:
    """consulting mode に切替。session 更新 + rich menu link + welcome reply。"""
    if deps.session_repo is None:
        logger.warning("cannot enter consulting: session_repo missing")
        await deps.line_client.reply_text(
            reply_token=event.reply_token, text="相談機能は現在利用できません。"
        )
        return
    await deps.session_repo.set_mode(
        line_user_id=event.line_user_id,
        family_id=deps.family_id,
        mode=MODE_CONSULTING,
    )
    # rich menu 切替 (失敗してもモード遷移は継続)
    if deps.rich_menu_id_consulting:
        try:
            await deps.line_client.link_richmenu_to_user(
                user_id=event.line_user_id,
                rich_menu_id=deps.rich_menu_id_consulting,
            )
        except Exception:
            logger.exception("failed to link consulting rich menu")
    await deps.line_client.reply_text(reply_token=event.reply_token, text=CONSULT_ENTER_REPLY)


async def _exit_consulting(event: LineTextEvent | LinePostbackEvent, deps: HandlerDeps) -> None:
    """consulting mode を解除。session 更新 + rich menu unlink + farewell reply。"""
    if deps.session_repo is None:
        logger.warning("cannot exit consulting: session_repo missing")
        await deps.line_client.reply_text(
            reply_token=event.reply_token, text="相談機能は現在利用できません。"
        )
        return
    await deps.session_repo.set_mode(
        line_user_id=event.line_user_id,
        family_id=deps.family_id,
        mode=MODE_NORMAL,
    )
    if deps.rich_menu_id_consulting:
        try:
            await deps.line_client.unlink_richmenu_from_user(user_id=event.line_user_id)
        except Exception:
            logger.exception("failed to unlink consulting rich menu")
    await deps.line_client.reply_text(reply_token=event.reply_token, text=CONSULT_EXIT_REPLY)


_WELCOME_TEXT = (
    "👋 はじめまして！ぴよログ分析 Bot です。\n"
    "\n"
    "ぴよログアプリから export した .txt を添付で送ると、\n"
    "授乳・睡眠・排泄等のサマリやグラフを返します。\n"
    "\n"
    "「ヘルプ」と送るとコマンド一覧が表示されます。"
)


async def _handle_postback(event: LinePostbackEvent, deps: HandlerDeps) -> None:
    """postback 振り分け。

    `action=consult&op=enter|exit` は mode 切替が必要なので line_handler 側で
    intercept する。それ以外 (summary / chart / help / undo) は postback_router へ。
    """
    data = event.data or ""
    if data.startswith("action=consult"):
        if "op=enter" in data:
            await _enter_consulting(event, deps)
            return
        if "op=exit" in data:
            await _exit_consulting(event, deps)
            return
        # op 未指定: 既定で enter
        await _enter_consulting(event, deps)
        return

    result = await handle_postback(
        event.data,
        repo=deps.repo,
        family_id=deps.family_id,
        now=deps.now_factory(),
    )
    if result.image_png is not None:
        await _send_image_or_fallback(event, deps, result)
        return
    await deps.line_client.reply_text(reply_token=event.reply_token, text=result.reply)


async def _handle_follow(event: LineFollowEvent, deps: HandlerDeps) -> None:
    """友だち追加: Welcome テキストを reply。

    rich menu の per-user 紐付けはここでは行わない (default rich menu を
    `setDefaultRichMenu` で global に設定する想定。`scripts/setup_richmenu.py`)。
    許可リスト判定は handle_event 側で済んでいる前提。
    """
    await deps.line_client.reply_text(reply_token=event.reply_token, text=_WELCOME_TEXT)


async def _send_image_or_fallback(event, deps: HandlerDeps, result) -> None:
    """画像送信。public_base_url 未設定 / image_store 未配線ならテキスト fallback。"""
    if not deps.public_base_url or deps.image_store is None:
        logger.warning(
            "image command but public_base_url or image_store unavailable; falling back to text"
        )
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=(
                f"{result.reply}\n"
                "(画像送信は公開 URL 未設定のため利用できません。"
                "PUBLIC_BASE_URL を設定してください)"
            ),
        )
        return
    image_id = deps.image_store.put(result.image_png)
    image_url = f"{deps.public_base_url}/api/line/image/{image_id}.png"
    try:
        await deps.line_client.reply_image(reply_token=event.reply_token, image_url=image_url)
    except Exception:
        logger.exception("reply_image failed; falling back to text")
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=f"{result.reply}\n(画像送信に失敗しました)",
        )


# ---------------------------------------------------------------------------
# File
# ---------------------------------------------------------------------------


_ACK_TEMPLATE = (
    "📥 ファイル「{filename}」を受信しました。\n取り込みを開始します。完了したらお知らせします。"
)

_SUCCESS_TEMPLATE = (
    "✅ 取り込み完了\n"
    "ファイル: {filename}\n"
    "期間: {date_from} 〜 {date_to}\n"
    "件数: {event_count} 件 ({days_count} 日分)"
)

_DUPLICATE_TEMPLATE = (
    "ℹ️ すでに取り込み済みのファイルでした (batch={batch_id})。\n重複登録はしていません。"
)

_INVALID_TEMPLATE = (
    "⚠️ 取り込みに失敗しました: {reason}\n"
    "ぴよログアプリからエクスポートした .txt をそのまま送ってください。"
)

_UNEXPECTED_TEMPLATE = "⚠️ 取り込み中にエラーが発生しました。少し時間を置いて再度お試しください。"


async def _handle_file(event: LineFileEvent, deps: HandlerDeps) -> None:
    # サイズ上限はここで早期チェック (ダウンロード前)
    if event.file_size and event.file_size > deps.upload_max_bytes:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=_INVALID_TEMPLATE.format(
                reason=f"ファイルサイズが上限 {deps.upload_max_bytes} bytes を超えています"
            ),
        )
        return

    # 拡張子は .txt 想定だが厳密拘束はしない (LINE で拡張子なしになる場合もある)
    await deps.line_client.reply_text(
        reply_token=event.reply_token,
        text=_ACK_TEMPLATE.format(filename=event.filename or "(no name)"),
    )

    to_user = event.line_user_id

    async def _job() -> None:
        try:
            data = await deps.line_client.fetch_message_content(message_id=event.message_id)
        except Exception as e:
            logger.exception("failed to fetch message content")
            await deps.line_client.push_text(
                to=to_user,
                text=_INVALID_TEMPLATE.format(reason=f"ファイル取得に失敗 ({e})"),
            )
            return

        try:
            outcome: ImportOutcome = await import_piyolog_bytes(
                repo=deps.repo,
                family_id=deps.family_id,
                source_user_id=event.line_user_id,
                child_id=deps.default_child_id,
                data=data,
                source_filename=event.filename or None,
                max_bytes=deps.upload_max_bytes,
            )
        except InvalidPiyologFileError as e:
            await deps.line_client.push_text(
                to=to_user,
                text=_INVALID_TEMPLATE.format(reason=str(e)),
            )
            return
        except DuplicateImportError as e:
            await deps.line_client.push_text(
                to=to_user,
                text=_DUPLICATE_TEMPLATE.format(batch_id=e.batch_id[:8]),
            )
            return
        except Exception:
            logger.exception("unexpected error during import")
            await deps.line_client.push_text(to=to_user, text=_UNEXPECTED_TEMPLATE)
            return

        days = outcome.parse_result.days
        if days:
            date_from = days[0].date.strftime("%Y/%m/%d")
            date_to = days[-1].date.strftime("%Y/%m/%d")
        else:
            date_from = date_to = "-"

        await deps.line_client.push_text(
            to=to_user,
            text=_SUCCESS_TEMPLATE.format(
                filename=event.filename or "(no name)",
                date_from=date_from,
                date_to=date_to,
                event_count=outcome.batch.event_count,
                days_count=len(days),
            ),
        )

    deps.schedule_background(_job)


# ---------------------------------------------------------------------------
# asyncio.create_task 用のフォールバック
# ---------------------------------------------------------------------------


def schedule_via_create_task(coro_factory: Callable[[], Awaitable[None]]) -> None:
    asyncio.create_task(coro_factory())
