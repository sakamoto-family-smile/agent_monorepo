"""POST /webhook — LINE Messaging API のコールバック。

挙動:
- 即時 200 OK を返す（個別 event の失敗は LINE 側を blocking しない）
- 署名検証失敗で 401
- LINE_* env 未設定で 503
- 認可されていない user は無視
- text: コマンド（検索 / 一覧 / 確定 / ヘルプ）
- file(csv): 取り込みプレビュー → 保留
- image: OCR → 抽出 → 確認フォーム URL を返信

LINE の 3 秒制約に対しては、低頻度の夫婦利用を前提に同期返信する。将来的な
高頻度化では Pub/Sub 非同期化に置き換える（design.md §10）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Request, status
from linebot.v3.webhooks import (
    FileMessageContent,
    ImageMessageContent,
    MessageEvent,
    TextMessageContent,
)

from app.deps import AppDeps
from app.line_client import InvalidSignatureError, LineBotClient, get_line_bot_client
from app.models import dedup_key
from app.services.csv_import import prepare_import
from app.services.messages import build_register_url, format_search_results, help_text
from app.services.ocr import extract_fields

logger = logging.getLogger(__name__)

router = APIRouter()

_CONFIRM_WORDS = {"確定", "はい", "ok", "OK", "登録する"}
_CANCEL_WORDS = {"キャンセル", "取消", "やめる", "いいえ"}


@router.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(default=""),
) -> dict[str, str]:
    """LINE Platform からの webhook を受け取り、即時 200 を返す。"""
    client = get_line_bot_client()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LINE channel is not configured",
        )

    body = await request.body()
    try:
        events = client.parse_events(body, x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid signature"
        ) from None

    deps: AppDeps = request.app.state.deps
    for event in events:
        try:
            _handle_event(client, event, deps)
        except Exception:  # pragma: no cover - 個別 event 失敗は握りつぶす
            logger.exception("error while handling LINE event: %r", event)

    return {"status": "ok"}


def _handle_event(client: LineBotClient, event: object, deps: AppDeps) -> None:
    if not isinstance(event, MessageEvent):
        return
    reply_token = event.reply_token
    if not reply_token:
        return
    user_id = event.source.user_id if event.source else ""

    # 認可: ホワイトリスト外は黙って無視（存在を悟らせない）。
    if not deps.settings.is_authorized(user_id):
        logger.info("ignored unauthorized user: %s", user_id)
        return

    message = event.message
    if isinstance(message, TextMessageContent):
        _handle_text(client, deps, reply_token, user_id, message.text)
    elif isinstance(message, FileMessageContent):
        _handle_file(client, deps, reply_token, user_id, message)
    elif isinstance(message, ImageMessageContent):
        _handle_image(client, deps, reply_token, message)


def _handle_text(
    client: LineBotClient,
    deps: AppDeps,
    reply_token: str,
    user_id: str,
    text: str,
) -> None:
    command = (text or "").strip()
    register_url = build_register_url(deps.settings.public_base_url)

    # 保留中の CSV インポートがあれば確定 / キャンセルを優先処理。
    if user_id in deps.pending_imports:
        if command in _CONFIRM_WORDS:
            drafts = deps.pending_imports.pop(user_id)
            created = deps.roster.import_drafts(drafts, created_by=user_id)
            client.reply_text(reply_token, [f"✅ {len(created)} 件を登録しました。"])
            return
        if command in _CANCEL_WORDS:
            deps.pending_imports.pop(user_id, None)
            client.reply_text(reply_token, ["インポートをキャンセルしました。"])
            return

    if command in {"ヘルプ", "help", "使い方", "登録"}:
        client.reply_text(reply_token, [help_text(register_url)])
        return

    if command in {"一覧", "list"}:
        results = deps.roster.list_all()
        client.reply_text(reply_token, [format_search_results(results, "全件")])
        return

    if command.startswith(("検索", "search")):
        query = command.split(maxsplit=1)
        keyword = query[1].strip() if len(query) > 1 else ""
        results = deps.roster.search(keyword)
        client.reply_text(reply_token, [format_search_results(results, keyword or "全件")])
        return

    # それ以外はヘルプを返す。
    client.reply_text(reply_token, [help_text(register_url)])


def _handle_file(
    client: LineBotClient,
    deps: AppDeps,
    reply_token: str,
    user_id: str,
    message: FileMessageContent,
) -> None:
    file_name = (message.file_name or "").lower()
    if not file_name.endswith(".csv"):
        client.reply_text(reply_token, ["CSV ファイル（.csv）を送ってください。"])
        return

    data = client.get_message_content(message.id)
    existing_keys = {dedup_key(e.name, e.address) for e in deps.roster.list_all()}
    preview = prepare_import(data, existing_keys)

    if preview.valid_count == 0:
        deps.pending_imports.pop(user_id, None)
        lines = [f"取り込める行がありませんでした。\n{preview.summary()}"]
        lines += _error_lines(preview)
        client.reply_text(reply_token, ["\n".join(lines)])
        return

    deps.pending_imports[user_id] = preview.valid_drafts
    lines = [
        f"📥 CSV を確認しました。\n{preview.summary()}",
        "",
        "この内容で登録する場合は「確定」、やめる場合は「キャンセル」と送ってください。",
    ]
    lines += _error_lines(preview)
    client.reply_text(reply_token, ["\n".join(lines)])


def _handle_image(
    client: LineBotClient,
    deps: AppDeps,
    reply_token: str,
    message: ImageMessageContent,
) -> None:
    data = client.get_message_content(message.id)
    text = deps.ocr_engine.recognize(data)
    draft = extract_fields(text)
    url = build_register_url(deps.settings.public_base_url, prefill=draft)

    summary = "🔍 写真から読み取りました。内容を確認して保存してください。"
    detail = "\n".join(
        filter(
            None,
            [
                f"名前: {draft.name}" if draft.name else "",
                f"〒{draft.zip}" if draft.zip else "",
                f"住所: {draft.address}" if draft.address else "",
            ],
        )
    ) or "（うまく読み取れませんでした。フォームで入力してください）"
    reply = f"{summary}\n\n{detail}"
    if url:
        reply += f"\n\n▼ 確認・保存フォーム\n{url}"
    client.reply_text(reply_token, [reply])


def _error_lines(preview: object) -> list[str]:
    """プレビューのエラー行を返信用テキストにする（最大 5 件）。"""
    errors = getattr(preview, "errors", [])
    if not errors:
        return []
    lines = ["", "⚠️ エラー行:"]
    for err in errors[:5]:
        lines.append(f"　{err.line} 行目: {err.reason}")
    if len(errors) > 5:
        lines.append(f"　… ほか {len(errors) - 5} 件")
    return lines


__all__ = ["router"]
