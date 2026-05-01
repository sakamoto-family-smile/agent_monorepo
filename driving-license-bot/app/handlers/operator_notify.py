"""運営者向け LINE Push 通知ヘルパ (Phase 2-B3)。

`OPERATOR_LINE_USER_IDS` (Secret Manager 管理) で指定された運営者の LINE
ユーザー ID 全員に Push Message を送る。バッチの pool_low_alert / 失敗時の
通知に使う。

設計判断:
- Reply Message ではなく Push を使う (バッチは Webhook context が無いため)
- Push は LINE 側でクォータ消費するため、呼び出し側で頻度を絞る (バッチ完了 1 回 / batch)
- 1 ユーザー失敗しても他に届け切るため、ユーザーごとに try/except で個別処理
- LINE 未設定の test 環境では silent skip
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from app.config import settings
from app.services.line_client import get_line_bot_client

logger = logging.getLogger(__name__)


def notify_operators(messages: list[str]) -> int:
    """全運営者に Push Message。届けた件数 (LINE クライアント呼び出し成功数) を返す。

    LINE 未設定 / 運営者未登録 / 全送信失敗でも例外は投げず 0 を返す。
    バッチ処理を止めないことを優先する。
    """
    if not messages:
        return 0

    operators: Iterable[str] = settings.operator_user_id_set
    if not operators:
        logger.info("notify_operators: operator_user_id_set is empty, skip")
        return 0

    client = get_line_bot_client()
    if client is None:
        logger.warning("notify_operators: LINE client unavailable, skip")
        return 0

    sent = 0
    for uid in operators:
        try:
            client.push_text(uid, messages)
            sent += 1
        except Exception:  # noqa: BLE001
            logger.exception("notify_operators: push failed uid=%s", uid)
    logger.info("notify_operators: sent=%d total_operators=%d", sent, len(set(operators)))
    return sent


__all__ = ["notify_operators"]
