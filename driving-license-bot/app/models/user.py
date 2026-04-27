"""ユーザードメインモデル。"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Goal(StrEnum):
    PROVISIONAL = "provisional"
    FULL = "full"


class UserStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    SCHEDULED_DELETION = "scheduled_deletion"


def _now() -> datetime:
    return datetime.now(UTC)


class User(BaseModel):
    """`/users/{internal_uid}` の Firestore ドキュメントを表す。"""

    internal_uid: str
    line_user_id: str
    line_login_sub: str | None = None  # Phase 2+ で利用
    display_name: str | None = None
    picture_url: str | None = None
    active_goal: Goal = Goal.PROVISIONAL
    created_at: datetime = Field(default_factory=_now)
    last_active_at: datetime = Field(default_factory=_now)
    status: UserStatus = UserStatus.ACTIVE
    scheduled_deletion_at: datetime | None = None
    consent_tos_version: int = 1
    consented_at: datetime | None = None
