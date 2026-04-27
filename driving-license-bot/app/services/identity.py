"""LINE User ID と internal_uid のマッピング。

DESIGN.md §8.1 / §8.2 に準拠。
mutation は `model_copy(update=...)` で行い直接代入は避ける（pydantic v2 の
validation を毎回通すため）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.models import Goal, User, UserStatus
from app.repositories.protocols import LineUserIndexRepo, UserRepo


class IdentityService:
    """LINE User ID 起点で User と internal_uid を取得・新規作成する。"""

    def __init__(self, users: UserRepo, index: LineUserIndexRepo) -> None:
        self._users = users
        self._index = index

    async def get_or_create(
        self,
        line_user_id: str,
        *,
        bot_channel_id: str = "",
        display_name: str | None = None,
        picture_url: str | None = None,
    ) -> User:
        """LINE User ID から User を取得。存在しなければ新規発行。"""
        internal_uid = await self._index.get_internal_uid(line_user_id)
        if internal_uid:
            existing = await self._users.get(internal_uid)
            if existing is not None:
                updates: dict[str, object] = {"last_active_at": datetime.now(UTC)}
                if display_name and not existing.display_name:
                    updates["display_name"] = display_name
                if picture_url and not existing.picture_url:
                    updates["picture_url"] = picture_url
                refreshed = existing.model_copy(update=updates)
                await self._users.upsert(refreshed)
                return refreshed
            # index は残っているが users が無い → 整合性回復のため再発行
            internal_uid = None

        # 新規発行
        new_uid = str(uuid.uuid4())
        user = User(
            internal_uid=new_uid,
            line_user_id=line_user_id,
            display_name=display_name,
            picture_url=picture_url,
            active_goal=Goal.PROVISIONAL,
            status=UserStatus.ACTIVE,
        )
        await self._users.upsert(user)
        await self._index.set_mapping(
            line_user_id, new_uid, bot_channel_id=bot_channel_id
        )
        return user

    async def switch_goal(self, internal_uid: str, goal: Goal) -> User | None:
        user = await self._users.get(internal_uid)
        if user is None:
            return None
        updated = user.model_copy(
            update={"active_goal": goal, "last_active_at": datetime.now(UTC)}
        )
        await self._users.upsert(updated)
        return updated
