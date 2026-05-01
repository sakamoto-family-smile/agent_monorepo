"""業務イベントの emit ヘルパ。

DESIGN.md §15.1.4 / §8.3 に対応。AnalyticsLogger を直接呼ばず、本モジュール
経由で emit することで:
- event_type / event_version の typo を防ぐ
- 失敗時に握りつぶしてアプリ動作を止めないラッパを集約
- 将来のスキーマ変更時に修正点が 1 ファイルに収まる

スキーマ対応 (analytics_platform.observability.schemas.BusinessEvent):
- emit_business_event(event_name=...) → fields["action"] にマップ
- emit_business_event(properties=...) → fields["attributes"] にマップ
- business_domain は本モジュールで "driving_license_bot" を固定で付与
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.instrumentation.setup import get_analytics_logger

logger = logging.getLogger(__name__)


# このアプリ全体に固定する business_domain。analytics-platform 側で
# driving_license_bot 由来のイベントをまとめて集計するための識別子。
BUSINESS_DOMAIN = "driving_license_bot"


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
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> None:
    """analytics-platform の business_event スキーマで emit。

    引数:
        event_name: ビジネス上のアクション名 (例: "quiz_started")。
            schema 上は ``action`` フィールドにマップ。
        properties: 任意の属性 dict。schema 上は ``attributes`` にマップ。
        resource_type / resource_id: 影響を与えたリソースの識別 (任意)。

    失敗しても例外を投げず、ログだけ残す（業務処理を止めないため）。
    """
    try:
        analytics = get_analytics_logger()
    except RuntimeError:
        # setup_observability() 未実行（テスト等）。silent skip。
        return
    try:
        fields: dict[str, Any] = {
            "business_domain": BUSINESS_DOMAIN,
            "action": event_name,
            "attributes": properties or {},
        }
        if resource_type is not None:
            fields["resource_type"] = resource_type
        if resource_id is not None:
            fields["resource_id"] = resource_id
        analytics.emit(
            event_type="business_event",
            event_version="1.0.0",
            severity="INFO",
            fields=fields,
            user_id=user_id,
            session_id=session_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("emit_business_event failed name=%s", event_name)


# ErrorCategory は schemas.py の Literal と同義 (循環 import 回避でローカル定義)
ErrorCategory = Literal["external_api", "internal", "validation", "timeout", "auth"]


def emit_error_event(
    *,
    error_type: str,
    error_message: str,
    error_category: ErrorCategory = "internal",
    error_code: str | None = None,
    is_retriable: bool = False,
    user_id: str | None = None,
    session_id: str | None = None,
    properties: dict[str, Any] | None = None,  # noqa: ARG001 — back-compat (schema 非対応)
) -> None:
    """error_event スキーマで emit。

    error_category は schema 上必須なので呼び出し側で明示するのが望ましい
    (default="internal")。``properties`` は schema 上の対応フィールドが無いため
    現状無視する (call site の back-compat のため signature には残す)。
    """
    try:
        analytics = get_analytics_logger()
    except RuntimeError:
        return
    try:
        fields: dict[str, Any] = {
            "error_type": error_type,
            "error_message": error_message,
            "error_category": error_category,
            "is_retriable": is_retriable,
        }
        if error_code is not None:
            fields["error_code"] = error_code
        analytics.emit(
            event_type="error_event",
            event_version="1.0.0",
            severity="ERROR",
            fields=fields,
            user_id=user_id,
            session_id=session_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("emit_error_event failed type=%s", error_type)


__all__ = [
    "BUSINESS_DOMAIN",
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
