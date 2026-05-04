"""Phase 3-A: SessionRepo のユニットテスト (SQLite in-memory)。"""

from __future__ import annotations

import pathlib
import tempfile

import pytest
from repositories.event_repo import EventRepo
from repositories.session_repo import (
    GAP_ASKED_CLARIFICATION,
    GAP_COMPLETED,
    MODE_CONSULTING,
    MODE_NORMAL,
    ROLE_ASSISTANT,
    ROLE_USER,
    SessionRepo,
)


@pytest.fixture
async def repo_pair():
    """EventRepo + SessionRepo (engine 共有)。"""
    with tempfile.TemporaryDirectory() as td:
        db_path = pathlib.Path(td) / "test.db"
        ev = EventRepo(database_url=f"sqlite+aiosqlite:///{db_path}")
        await ev.initialize()
        sr = SessionRepo(engine=ev.engine)
        yield sr
        await ev.dispose()


@pytest.mark.asyncio
async def test_get_mode_default_normal(repo_pair: SessionRepo) -> None:
    """未登録なら MODE_NORMAL を返す。"""
    mode = await repo_pair.get_mode(line_user_id="U1")
    assert mode == MODE_NORMAL


@pytest.mark.asyncio
async def test_set_mode_consulting(repo_pair: SessionRepo) -> None:
    """consulting に切替えると consulting_since がセットされる。"""
    s = await repo_pair.set_mode(line_user_id="U1", family_id="f1", mode=MODE_CONSULTING)
    assert s.mode == MODE_CONSULTING
    assert s.consulting_since is not None
    assert s.family_id == "f1"


@pytest.mark.asyncio
async def test_set_mode_back_to_normal_clears_state(repo_pair: SessionRepo) -> None:
    """consulting → normal で consulting_since と current_conversation_id がクリア。"""
    await repo_pair.set_mode(line_user_id="U1", family_id="f1", mode=MODE_CONSULTING)
    conv = await repo_pair.start_conversation(family_id="f1", line_user_id="U1")
    s_before = await repo_pair.get_session(line_user_id="U1")
    assert s_before is not None
    assert s_before.current_conversation_id == conv.conversation_id
    s_after = await repo_pair.set_mode(line_user_id="U1", family_id="f1", mode=MODE_NORMAL)
    assert s_after.mode == MODE_NORMAL
    assert s_after.consulting_since is None
    assert s_after.current_conversation_id is None


@pytest.mark.asyncio
async def test_set_mode_invalid_raises(repo_pair: SessionRepo) -> None:
    with pytest.raises(ValueError):
        await repo_pair.set_mode(line_user_id="U1", family_id="f1", mode="invalid")


@pytest.mark.asyncio
async def test_start_conversation_links_session(repo_pair: SessionRepo) -> None:
    conv = await repo_pair.start_conversation(family_id="f1", line_user_id="U1")
    assert conv.conversation_id
    assert conv.message_count == 0
    s = await repo_pair.get_session(line_user_id="U1")
    assert s is not None
    assert s.current_conversation_id == conv.conversation_id


@pytest.mark.asyncio
async def test_append_message_increments_counters(repo_pair: SessionRepo) -> None:
    conv = await repo_pair.start_conversation(family_id="f1", line_user_id="U1")
    await repo_pair.append_message(
        conversation_id=conv.conversation_id, role=ROLE_USER, content="hi"
    )
    await repo_pair.append_message(
        conversation_id=conv.conversation_id,
        role=ROLE_ASSISTANT,
        content="hello",
        llm_model="gemini-2.5-pro",
        input_tokens=100,
        output_tokens=50,
        cache_read_tokens=200,
        capability_gap=GAP_COMPLETED,
    )
    history = await repo_pair.fetch_history(conversation_id=conv.conversation_id)
    assert len(history) == 2
    assert history[0].role == ROLE_USER
    assert history[1].role == ROLE_ASSISTANT
    assert history[1].input_tokens == 100
    assert history[1].capability_gap == GAP_COMPLETED


@pytest.mark.asyncio
async def test_fetch_history_orders_by_created_at(repo_pair: SessionRepo) -> None:
    conv = await repo_pair.start_conversation(family_id="f1", line_user_id="U1")
    msgs = ["a", "b", "c"]
    for m in msgs:
        await repo_pair.append_message(
            conversation_id=conv.conversation_id, role=ROLE_USER, content=m
        )
    history = await repo_pair.fetch_history(conversation_id=conv.conversation_id)
    assert [m.content for m in history] == msgs


@pytest.mark.asyncio
async def test_close_conversation(repo_pair: SessionRepo) -> None:
    conv = await repo_pair.start_conversation(family_id="f1", line_user_id="U1")
    await repo_pair.close_conversation(conversation_id=conv.conversation_id, summary="test summary")
    # close 後も history は読める (削除はしない、論理 close のみ)
    history = await repo_pair.fetch_history(conversation_id=conv.conversation_id)
    assert history == []  # メッセージ無し case


@pytest.mark.asyncio
async def test_capability_gap_recorded(repo_pair: SessionRepo) -> None:
    """capability_gap タグが正しく保存される (機能改善ログ用途)。"""
    conv = await repo_pair.start_conversation(family_id="f1", line_user_id="U1")
    await repo_pair.append_message(
        conversation_id=conv.conversation_id,
        role=ROLE_ASSISTANT,
        content="どの期間ですか?",
        capability_gap=GAP_ASKED_CLARIFICATION,
    )
    history = await repo_pair.fetch_history(conversation_id=conv.conversation_id)
    assert history[0].capability_gap == GAP_ASKED_CLARIFICATION
