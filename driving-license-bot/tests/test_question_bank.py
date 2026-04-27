"""InMemoryQuestionBank のテスト（pgvector 実装は別 PR で接続テスト）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.repositories.question_bank import (
    InMemoryQuestionBank,
    StoredQuestion,
)


def _stored(
    *,
    qid: str,
    embedding: list[float],
    category: str = "rules",
    body_hash: str = "sha256:dummy",
    status: str = "needs_review",
    goals: list[str] | None = None,
) -> StoredQuestion:
    return StoredQuestion(
        question_id=qid,
        version=1,
        body_hash=body_hash,
        embedding=embedding,
        applicable_goals=goals or ["provisional", "full"],
        category=category,
        difficulty="basic",
        status=status,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_add_and_get() -> None:
    bank = InMemoryQuestionBank()
    q = _stored(qid="q1", embedding=[1.0, 0.0, 0.0])
    await bank.add(q)
    fetched = await bank.get("q1")
    assert fetched is not None
    assert fetched.question_id == "q1"


@pytest.mark.asyncio
async def test_get_returns_none_when_absent() -> None:
    bank = InMemoryQuestionBank()
    assert await bank.get("nonexistent") is None


@pytest.mark.asyncio
async def test_find_similar_orders_by_score_desc() -> None:
    bank = InMemoryQuestionBank()
    await bank.add(_stored(qid="q1", embedding=[1.0, 0.0, 0.0]))
    await bank.add(_stored(qid="q2", embedding=[0.7, 0.7, 0.0]))
    await bank.add(_stored(qid="q3", embedding=[0.0, 0.0, 1.0]))

    hits = await bank.find_similar([1.0, 0.0, 0.0], top_k=3)
    assert [h.stored.question_id for h in hits] == ["q1", "q2", "q3"]
    assert hits[0].score == pytest.approx(1.0, abs=1e-6)
    assert 0 < hits[1].score < hits[0].score
    assert hits[2].score < hits[1].score


@pytest.mark.asyncio
async def test_find_similar_filters_by_category() -> None:
    bank = InMemoryQuestionBank()
    await bank.add(_stored(qid="q_rules", embedding=[1.0, 0.0], category="rules"))
    await bank.add(_stored(qid="q_signs", embedding=[1.0, 0.0], category="signs"))

    hits = await bank.find_similar([1.0, 0.0], top_k=5, category="signs")
    assert [h.stored.question_id for h in hits] == ["q_signs"]


@pytest.mark.asyncio
async def test_find_similar_top_k_limit() -> None:
    bank = InMemoryQuestionBank()
    for i in range(10):
        await bank.add(_stored(qid=f"q{i}", embedding=[1.0 - i * 0.05, 0.1]))
    hits = await bank.find_similar([1.0, 0.0], top_k=3)
    assert len(hits) == 3


@pytest.mark.asyncio
async def test_find_similar_handles_empty_bank() -> None:
    bank = InMemoryQuestionBank()
    hits = await bank.find_similar([1.0, 0.0], top_k=5)
    assert hits == []


@pytest.mark.asyncio
async def test_find_similar_handles_dimension_mismatch_gracefully() -> None:
    """次元不一致時に 0.0 を返し、ハードフェイルしない。"""
    bank = InMemoryQuestionBank()
    await bank.add(_stored(qid="q1", embedding=[1.0, 0.0, 0.0]))
    hits = await bank.find_similar([1.0, 0.0], top_k=5)  # 異なる次元
    assert hits[0].score == 0.0


@pytest.mark.asyncio
async def test_find_by_body_hash() -> None:
    bank = InMemoryQuestionBank()
    await bank.add(_stored(qid="q1", embedding=[1.0], body_hash="sha256:aaa"))
    await bank.add(_stored(qid="q2", embedding=[1.0], body_hash="sha256:bbb"))
    found = await bank.find_by_body_hash("sha256:bbb")
    assert found is not None
    assert found.question_id == "q2"


@pytest.mark.asyncio
async def test_count_with_filters() -> None:
    bank = InMemoryQuestionBank()
    await bank.add(
        _stored(qid="q1", embedding=[1.0], status="published", goals=["provisional"])
    )
    await bank.add(
        _stored(qid="q2", embedding=[1.0], status="needs_review", goals=["full"])
    )
    await bank.add(
        _stored(
            qid="q3",
            embedding=[1.0],
            status="published",
            goals=["provisional", "full"],
        )
    )
    assert await bank.count() == 3
    assert await bank.count(status="published") == 2
    assert await bank.count(status="needs_review") == 1
    assert await bank.count(applicable_goal="provisional") == 2
    assert await bank.count(applicable_goal="full") == 2
    assert await bank.count(status="published", applicable_goal="full") == 1


@pytest.mark.asyncio
async def test_add_overwrites_existing_id() -> None:
    bank = InMemoryQuestionBank()
    await bank.add(_stored(qid="q1", embedding=[1.0], category="rules"))
    await bank.add(_stored(qid="q1", embedding=[1.0], category="signs"))
    fetched = await bank.get("q1")
    assert fetched is not None
    assert fetched.category == "signs"
