"""ルート / サービス層から呼ぶ簡易ヘルパー。

`emit_business` / `emit_error` は AnalyticsLogger 未初期化時もエラーにせず
静かに無視する (テストや CLI 経路でも安全に呼べる)。
"""

from __future__ import annotations

import logging
from typing import Any

from .setup import get_analytics_logger

logger = logging.getLogger(__name__)


def _safe_logger():
    try:
        return get_analytics_logger()
    except RuntimeError:
        return None


def emit_business(
    *,
    domain: str,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    attributes: dict[str, Any] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    severity: str = "INFO",
) -> None:
    al = _safe_logger()
    if al is None:
        return
    try:
        al.emit(
            event_type="business_event",
            event_version="1.0.0",
            severity=severity,
            fields={
                "business_domain": domain,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "attributes": attributes or {},
            },
            user_id=user_id,
            session_id=session_id,
        )
    except Exception:
        logger.exception("emit_business failed (non-fatal)")


def emit_error(
    *,
    error: BaseException,
    category: str = "internal",
    is_retriable: bool = False,
    user_id: str | None = None,
    session_id: str | None = None,
    severity: str = "ERROR",
) -> None:
    al = _safe_logger()
    if al is None:
        return
    try:
        al.emit(
            event_type="error_event",
            event_version="1.0.0",
            severity=severity,
            fields={
                "error_type": type(error).__name__,
                "error_message": str(error)[:1000],
                "error_category": category,
                "is_retriable": is_retriable,
            },
            user_id=user_id,
            session_id=session_id,
        )
    except Exception:
        logger.exception("emit_error failed (non-fatal)")


def emit_security(
    *,
    guard_name: str,
    check_type: str,
    action_taken: str,
    risk_score: float | None = None,
    matched_rules: list[str] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    severity: str = "WARN",
) -> None:
    al = _safe_logger()
    if al is None:
        return
    try:
        al.emit(
            event_type="security_event",
            event_version="1.0.0",
            severity=severity,
            fields={
                "guard_name": guard_name,
                "check_type": check_type,
                "action_taken": action_taken,
                "risk_score": risk_score,
                "matched_rules": matched_rules or [],
            },
            user_id=user_id,
            session_id=session_id,
        )
    except Exception:
        logger.exception("emit_security failed (non-fatal)")
