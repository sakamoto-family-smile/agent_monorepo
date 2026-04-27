"""CommandRouter のエンドツーエンド (in-memory) テスト。"""

from __future__ import annotations

import pytest

from app.handlers.command_router import HandlerDeps
from app.handlers.disclaimer import DELETE_CONFIRMATION, DISCLAIMER_FOOTER, HELP_TEXT
from app.models import Goal, UserStatus
from app.repositories import InMemoryRepoBundle

LINE_USER = "U" + "0" * 32


async def _send(deps: HandlerDeps, text: str) -> list[str]:
    from app.handlers.command_router import CommandRouter

    return await CommandRouter(deps).dispatch_text(line_user_id=LINE_USER, text=text)


@pytest.mark.asyncio
async def test_help_returns_help_text(deps: HandlerDeps) -> None:
    replies = await _send(deps, "ヘルプ")
    assert len(replies) == 1
    assert "使い方" in replies[0]
    assert replies[0] == HELP_TEXT


@pytest.mark.asyncio
async def test_quiz_command_starts_question_session(
    deps: HandlerDeps, repo_bundle: InMemoryRepoBundle
) -> None:
    replies = await _send(deps, "クイズ")
    assert len(replies) == 1
    assert "回答は番号" in replies[0]
    # active session が作られている
    user = await repo_bundle.users.get(
        await repo_bundle.line_user_index.get_internal_uid(LINE_USER)
    )
    assert user is not None
    active = await repo_bundle.sessions.get_active(user.internal_uid)
    assert active is not None
    assert active.current_question_id is not None


@pytest.mark.asyncio
async def test_correct_answer_updates_history_and_returns_explanation(
    deps: HandlerDeps, repo_bundle: InMemoryRepoBundle
) -> None:
    await _send(deps, "クイズ")
    internal_uid = await repo_bundle.line_user_index.get_internal_uid(LINE_USER)
    assert internal_uid
    active = await repo_bundle.sessions.get_active(internal_uid)
    assert active is not None
    qid = active.current_question_id
    assert qid is not None
    correct_idx = next(q for q in deps.pool.all() if q.id == qid).correct
    answer_text = str(correct_idx + 1)

    replies = await _send(deps, answer_text)
    assert len(replies) == 1
    assert ("正解" in replies[0]) or ("不正解" in replies[0])
    assert "▼ 解説" in replies[0]
    assert "▼ 根拠" in replies[0]
    assert DISCLAIMER_FOOTER in replies[0]
    history = await repo_bundle.answer_histories.get(internal_uid, qid)
    assert history is not None
    assert history.attempt_count == 1


@pytest.mark.asyncio
async def test_true_false_keyword_works(deps: HandlerDeps) -> None:
    await _send(deps, "クイズ")
    replies = await _send(deps, "正しい")
    assert "解説" in replies[0]


@pytest.mark.asyncio
async def test_mode_switch_toggles_active_goal(
    deps: HandlerDeps, repo_bundle: InMemoryRepoBundle
) -> None:
    await _send(deps, "ヘルプ")  # ユーザー作成
    internal_uid = await repo_bundle.line_user_index.get_internal_uid(LINE_USER)
    assert internal_uid
    user_before = await repo_bundle.users.get(internal_uid)
    assert user_before is not None
    assert user_before.active_goal is Goal.PROVISIONAL

    replies = await _send(deps, "モード切替")
    assert len(replies) == 1
    assert "本免" in replies[0]
    user_after = await repo_bundle.users.get(internal_uid)
    assert user_after is not None
    assert user_after.active_goal is Goal.FULL


@pytest.mark.asyncio
async def test_mode_set_explicit(deps: HandlerDeps, repo_bundle: InMemoryRepoBundle) -> None:
    replies = await _send(deps, "本免")
    internal_uid = await repo_bundle.line_user_index.get_internal_uid(LINE_USER)
    user = await repo_bundle.users.get(internal_uid)  # type: ignore[arg-type]
    assert user is not None
    assert user.active_goal is Goal.FULL
    assert "本免" in replies[0]


@pytest.mark.asyncio
async def test_data_deletion_clears_state(
    deps: HandlerDeps, repo_bundle: InMemoryRepoBundle
) -> None:
    await _send(deps, "クイズ")
    internal_uid = await repo_bundle.line_user_index.get_internal_uid(LINE_USER)
    assert internal_uid
    # 削除実行
    replies = await _send(deps, "データを削除")
    assert replies == [DELETE_CONFIRMATION]

    # index は外れている
    assert await repo_bundle.line_user_index.get_internal_uid(LINE_USER) is None
    # session / history はクリア
    assert await repo_bundle.sessions.get_active(internal_uid) is None
    assert await repo_bundle.answer_histories.list_recent(internal_uid) == []
    # user 本体は scheduled_deletion 状態で残る
    user = await repo_bundle.users.get(internal_uid)
    assert user is not None
    assert user.status is UserStatus.SCHEDULED_DELETION
    assert user.scheduled_deletion_at is not None


@pytest.mark.asyncio
async def test_unknown_text_returns_help_hint(deps: HandlerDeps) -> None:
    replies = await _send(deps, "なにこれ？？")
    assert "コマンドが認識できませんでした" in replies[0]


@pytest.mark.asyncio
async def test_quiz_excludes_recently_answered(
    deps: HandlerDeps, repo_bundle: InMemoryRepoBundle
) -> None:
    """直近 5 件除外: 出題された問題は次回直後の出題から除外される。"""
    seen: set[str] = set()
    for _ in range(5):
        await _send(deps, "クイズ")
        internal_uid = await repo_bundle.line_user_index.get_internal_uid(LINE_USER)
        assert internal_uid
        active = await repo_bundle.sessions.get_active(internal_uid)
        assert active is not None
        seen.add(active.current_question_id)  # type: ignore[arg-type]
        # 直前の出題を消費して回答（正解 / 不正解いずれでもよい）
        await _send(deps, "1")
    assert len(seen) == 5  # 5 連続で同じ問題が出ない
