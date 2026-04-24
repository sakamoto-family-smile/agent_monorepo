"""LINE Messaging API (Push Message) notifier.

Migration history:
  - 2025/03/31: LINE Notify が廃止されたため、本モジュールは LINE Messaging API
    (Bot channel) を用いた Push Message 送信に移行済。旧 `LINE_NOTIFY_TOKEN` は
    設定自体は残すが、利用されていれば起動時に deprecation 警告を出す。

Future integration:
  - tech-news-agent Phase 3 のセキュリティドメイン着手時に、本モジュールの
    Flex Message 構築ロジックを monorepo 共通の `line-publisher/` に切り出して
    共通化する予定。現時点ではスコープを抑えて local 実装とする。

Interface:
  - `send_message(text: str) -> bool` は既存呼び出し側 (digest / analyzer) と
    後方互換。戻り値 True は「少なくとも 1 人に送信成功」の意味。
  - 認証情報 (`LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN`) または
    宛先 (`LINE_USER_IDS`) が未設定なら False を返し、例外は投げない。
"""
from __future__ import annotations

import logging

from ..config import settings

logger = logging.getLogger(__name__)


_MAX_PUSH_CHARS = 4900  # LINE TextMessage の上限は 5000 字、safety margin として 4900


def _trim(text: str, limit: int = _MAX_PUSH_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n...(以下省略)"


def _recipient_user_ids() -> list[str]:
    raw = settings.line_user_ids or ""
    return [uid.strip() for uid in raw.split(",") if uid.strip()]


def _warn_if_legacy_notify_token_set() -> None:
    if settings.line_notify_token:
        logger.warning(
            "LINE_NOTIFY_TOKEN is set but LINE Notify was terminated on 2025/03/31. "
            "The token is ignored. Please migrate to LINE_CHANNEL_SECRET / "
            "LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_IDS."
        )


async def send_message(text: str) -> bool:
    """Push a plain-text message to all configured LINE user IDs.

    Returns True if at least one push succeeded, False if not configured or
    all pushes failed.
    """
    _warn_if_legacy_notify_token_set()

    if not settings.line_channel_access_token or not settings.line_channel_secret:
        logger.debug(
            "LINE Messaging API not configured "
            "(missing LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN); skipping"
        )
        return False

    recipients = _recipient_user_ids()
    if not recipients:
        logger.debug("LINE_USER_IDS not set; skipping LINE notification")
        return False

    try:
        from linebot.v3.messaging import (
            AsyncApiClient,
            AsyncMessagingApi,
            Configuration,
            PushMessageRequest,
            TextMessage,
        )
    except ImportError as exc:
        logger.error("line-bot-sdk is required for LINE notifications: %s", exc)
        return False

    config = Configuration(access_token=settings.line_channel_access_token)
    api_client = AsyncApiClient(config)
    messaging = AsyncMessagingApi(api_client)

    trimmed = _trim(text)
    sent = 0
    try:
        for uid in recipients:
            try:
                await messaging.push_message(
                    PushMessageRequest(to=uid, messages=[TextMessage(text=trimmed)])
                )
                sent += 1
            except Exception as exc:
                # 他の受信者への送信は続行する
                logger.error(
                    "LINE push to %s***%s failed: %s",
                    uid[:4],
                    uid[-4:] if len(uid) > 8 else "",
                    exc,
                )
    finally:
        try:
            await api_client.close()
        except Exception:
            pass

    if sent == 0:
        logger.error("LINE Messaging API: all %d push requests failed", len(recipients))
    else:
        logger.info(
            "LINE Messaging API: %d/%d recipients notified", sent, len(recipients)
        )
    return sent > 0
