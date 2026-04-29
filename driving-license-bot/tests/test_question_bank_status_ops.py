"""C2: InMemoryQuestionBank の list_by_status / update_status をテスト。

pgvector_impl は実 Postgres が必要なため、CI では in-memory のみ。
pgvector の実機 smoke は scripts/verify_question_bank.py 参照。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.repositories.question_bank import InMemoryQuestionBank, StoredQuestion


def _make(qid: str, status: str = "needs_review", offset_min: int = 0) -> StoredQuestion:
    return StoredQuestion(
        question_id=qid,
        version=1,
        body_hash=f"h-{qid}",
        embedding=[0.0] * 768,
        applicable_goals=["provisional"],
        category="rules",
        difficulty="standard",
        status=status,
        created_at=datetime.now(UTC) - timedelta(minutes=offset_min),
    )


@pytest.mark.asyncio
async def test_list_by_status_filters_and_orders() -> None:
    bank = InMemoryQuestionBank()
    await bank.add(_make("a", status="needs_review", offset_min=10))
    await bank.add(_make("b", status="needs_review", offset_min=0))
    await bank.add(_make("c", status="published"))

    pending = await bank.list_by_status("needs_review")
    assert [q.question_id for q in pending] == ["b", "a"]  # newer first

    published = await bank.list_by_status("published")
    assert [q.question_id for q in published] == ["c"]

    archived = await bank.list_by_status("archived")
    assert archived == []


@pytest.mark.asyncio
async def test_list_by_status_respects_limit() -> None:
    bank = InMemoryQuestionBank()
    for i in range(5):
        await bank.add(_make(f"q{i}", offset_min=i))
    out = await bank.list_by_status("needs_review", limit=2)
    assert len(out) == 2


@pytest.mark.asyncio
async def test_update_status_returns_true_on_success() -> None:
    bank = InMemoryQuestionBank()
    await bank.add(_make("a", status="needs_review"))
    ok = await bank.update_status("a", "published")
    assert ok is True
    after = await bank.get("a")
    assert after is not None and after.status == "published"


@pytest.mark.asyncio
async def test_update_status_false_when_missing() -> None:
    bank = InMemoryQuestionBank()
    ok = await bank.update_status("nonexistent", "published")
    assert ok is False
