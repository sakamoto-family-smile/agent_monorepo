"""IdentityService のテスト。"""

from __future__ import annotations

import pytest

from app.models import Goal, UserStatus
from app.repositories import InMemoryRepoBundle
from app.services.identity import IdentityService


@pytest.mark.asyncio
async def test_get_or_create_creates_new_user() -> None:
    bundle = InMemoryRepoBundle()
    svc = IdentityService(bundle.users, bundle.line_user_index)

    user = await svc.get_or_create("U" + "a" * 32)

    assert user.line_user_id == "U" + "a" * 32
    assert user.internal_uid
    assert user.active_goal is Goal.PROVISIONAL
    assert user.status is UserStatus.ACTIVE
    # index にも紐付け
    mapped = await bundle.line_user_index.get_internal_uid("U" + "a" * 32)
    assert mapped == user.internal_uid


@pytest.mark.asyncio
async def test_get_or_create_returns_existing_user() -> None:
    bundle = InMemoryRepoBundle()
    svc = IdentityService(bundle.users, bundle.line_user_index)

    first = await svc.get_or_create("U" + "b" * 32)
    second = await svc.get_or_create("U" + "b" * 32)

    assert first.internal_uid == second.internal_uid
    # User は重複作成されない
    assert (
        len({first.internal_uid, second.internal_uid}) == 1
    )


@pytest.mark.asyncio
async def test_switch_goal_updates_active_goal() -> None:
    bundle = InMemoryRepoBundle()
    svc = IdentityService(bundle.users, bundle.line_user_index)

    user = await svc.get_or_create("U" + "c" * 32)
    assert user.active_goal is Goal.PROVISIONAL

    updated = await svc.switch_goal(user.internal_uid, Goal.FULL)
    assert updated is not None
    assert updated.active_goal is Goal.FULL

    # 取り出しても永続化されている
    persisted = await bundle.users.get(user.internal_uid)
    assert persisted is not None
    assert persisted.active_goal is Goal.FULL


@pytest.mark.asyncio
async def test_switch_goal_returns_none_for_unknown_uid() -> None:
    bundle = InMemoryRepoBundle()
    svc = IdentityService(bundle.users, bundle.line_user_index)

    result = await svc.switch_goal("nonexistent", Goal.FULL)
    assert result is None
