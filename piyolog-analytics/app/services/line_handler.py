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
from services.command_router import handle_text_command
from services.import_service import (
    DuplicateImportError,
    ImportOutcome,
    InvalidPiyologFileError,
    import_piyolog_bytes,
)
from services.line_client import LineBotClient, LineEvent, LineFileEvent, LineTextEvent

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
    else:
        logger.warning("unsupported event type: %r", event)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


async def _handle_text(event: LineTextEvent, deps: HandlerDeps) -> None:
    result = await handle_text_command(
        event.text,
        repo=deps.repo,
        family_id=deps.family_id,
        now=deps.now_factory(),
    )
    await deps.line_client.reply_text(
        reply_token=event.reply_token, text=result.reply
    )


# ---------------------------------------------------------------------------
# File
# ---------------------------------------------------------------------------


_ACK_TEMPLATE = (
    "📥 ファイル「{filename}」を受信しました。\n"
    "取り込みを開始します。完了したらお知らせします。"
)

_SUCCESS_TEMPLATE = (
    "✅ 取り込み完了\n"
    "ファイル: {filename}\n"
    "期間: {date_from} 〜 {date_to}\n"
    "件数: {event_count} 件 ({days_count} 日分)"
)

_DUPLICATE_TEMPLATE = (
    "ℹ️ すでに取り込み済みのファイルでした (batch={batch_id})。\n"
    "重複登録はしていません。"
)

_INVALID_TEMPLATE = (
    "⚠️ 取り込みに失敗しました: {reason}\n"
    "ぴよログアプリからエクスポートした .txt をそのまま送ってください。"
)

_UNEXPECTED_TEMPLATE = (
    "⚠️ 取り込み中にエラーが発生しました。少し時間を置いて再度お試しください。"
)


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
            data = await deps.line_client.fetch_message_content(
                message_id=event.message_id
            )
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
