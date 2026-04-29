"""業務イベントの emit ヘルパ。

DESIGN.md §15.1.4 / §8.3 に対応。AnalyticsLogger を直接呼ばず、本モジュール
経由で emit することで:
- event_type / event_version の typo を防ぐ
- 失敗時に握りつぶしてアプリ動作を止めないラッパを集約
- 将来のスキーマ変更時に修正点が 1 ファイルに収まる
"""

from __future__ import annotations

import logging
from typing import Any

from app.instrumentation.setup import get_analytics_logger

logger = logging.getLogger(__name__)


# ---- business_event の event_name 定義（DESIGN.md §15.1.4 と整合） ----

EVENT_QUIZ_STARTED = "quiz_started"
EVENT_QUIZ_ANSWERED = "quiz_answered"
EVENT_QUIZ_COMPLETED = "quiz_completed"
EVENT_MODE_SWITCHED = "mode_switched"
EVENT_MOCK_STARTED = "mock_started"
EVENT_MOCK_COMPLETED = "mock_completed"
EVENT_USER_DATA_DELETED = "user_data_deleted"
EVENT_BLOCK_EVENT_RECEIVED = "block_event_received"
EVENT_FOLLOW_EVENT_RECEIVED = "follow_event_received"
# Phase 2-C2: 人間レビュー
EVENT_QUESTION_PUBLISHED = "question_published"
EVENT_HUMAN_REVIEW_DECIDED = "human_review_decided"


def emit_business_event(
    *,
    event_name: str,
    properties: dict[str, Any] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """analytics-platform の business_event スキーマで emit。

    失敗しても例外を投げず、ログだけ残す（業務処理を止めないため）。
    """
    try:
        analytics = get_analytics_logger()
    except RuntimeError:
        # setup_observability() 未実行（テスト等）。silent skip。
        return
    try:
        analytics.emit(
            event_type="business_event",
            event_version="1.0.0",
            severity="INFO",
            fields={
                "event_name": event_name,
                "properties": properties or {},
            },
            user_id=user_id,
            session_id=session_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("emit_business_event failed name=%s", event_name)


def emit_error_event(
    *,
    error_type: str,
    error_message: str,
    user_id: str | None = None,
    session_id: str | None = None,
    properties: dict[str, Any] | None = None,
) -> None:
    """error_event スキーマで emit。"""
    try:
        analytics = get_analytics_logger()
    except RuntimeError:
        return
    try:
        analytics.emit(
            event_type="error_event",
            event_version="1.0.0",
            severity="ERROR",
            fields={
                "error_type": error_type,
                "error_message": error_message,
                "properties": properties or {},
            },
            user_id=user_id,
            session_id=session_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("emit_error_event failed type=%s", error_type)


__all__ = [
    "EVENT_BLOCK_EVENT_RECEIVED",
    "EVENT_FOLLOW_EVENT_RECEIVED",
    "EVENT_HUMAN_REVIEW_DECIDED",
    "EVENT_MOCK_COMPLETED",
    "EVENT_MOCK_STARTED",
    "EVENT_MODE_SWITCHED",
    "EVENT_QUESTION_PUBLISHED",
    "EVENT_QUIZ_ANSWERED",
    "EVENT_QUIZ_COMPLETED",
    "EVENT_QUIZ_STARTED",
    "EVENT_USER_DATA_DELETED",
    "emit_business_event",
    "emit_error_event",
]
