"""X1: BankBackedQuestionPool の挙動。"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from app.models import Choice, Question, QuestionFormat, Source
from app.models.question import SourceType
from app.repositories.question_bank import InMemoryQuestionBank, StoredQuestion
from app.repositories.question_pool import (
    BankBackedQuestionPool,
    QuestionPoolLike,
)
from app.repositories.question_repo import InMemoryQuestionRepo


def _make_stored(qid: str, status: str = "published", goals=None) -> StoredQuestion:
    return StoredQuestion(
        question_id=qid,
        version=1,
        body_hash=f"sha256:{qid}",
        embedding=[0.1] * 768,
        applicable_goals=goals or ["provisional", "full"],
        category="rules",
        difficulty="standard",
        status=status,
        created_at=datetime.now(UTC),
    )


def _make_question(qid: str, goals=None) -> Question:
    return Question(
        id=qid,
        version=1,
        body=f"問題本文 {qid}",
        format=QuestionFormat.TRUE_FALSE,
        choices=[Choice(index=0, text="正しい"), Choice(index=1, text="誤り")],
        correct=0,
        explanation="解説",
        applicable_goals=goals or ["provisional", "full"],
        difficulty="standard",
        category="rules",
        sources=[
            Source(
                type=SourceType.LAW,
                title="道路交通法",
                url="https://elaws.e-gov.go.jp/document?lawid=335AC0000000105",
                quoted_text="...",
            )
        ],
    )


@pytest.mark.asyncio
async def test_refresh_loads_published_only() -> None:
    bank = InMemoryQuestionBank()
    repo = InMemoryQuestionRepo()
    await bank.add(_make_stored("q_pub_1", status="published"))
    await bank.add(_make_stored("q_pub_2", status="published"))
    await bank.add(_make_stored("q_review", status="needs_review"))
    await bank.add(_make_stored("q_rej", status="rejected"))
    for qid in ("q_pub_1", "q_pub_2", "q_review", "q_rej"):
        await repo.upsert(_make_question(qid))

    pool = BankBackedQuestionPool(bank, repo)
    n = await pool.refresh()
    assert n == 2
    assert len(pool) == 2
    ids = {q.id for q in pool.all()}
    assert ids == {"q_pub_1", "q_pub_2"}


@pytest.mark.asyncio
async def test_refresh_skips_missing_body() -> None:
    """bank に published があるが repo に本文がない → スキップしてカウント。"""
    bank = InMemoryQuestionBank()
    repo = InMemoryQuestionRepo()
    await bank.add(_make_stored("q_with_body", status="published"))
    await bank.add(_make_stored("q_no_body", status="published"))
    await repo.upsert(_make_question("q_with_body"))
    # q_no_body は repo に未登録

    pool = BankBackedQuestionPool(bank, repo)
    n = await pool.refresh()
    assert n == 1
    assert pool.get("q_no_body") is None
    assert pool.get("q_with_body") is not None


@pytest.mark.asyncio
async def test_pick_filters_by_goal() -> None:
    bank = InMemoryQuestionBank()
    repo = InMemoryQuestionRepo()
    await bank.add(
        _make_stored("q_full_only", status="published", goals=["full"])
    )
    await bank.add(
        _make_stored("q_provisional_only", status="published", goals=["provisional"])
    )
    await repo.upsert(_make_question("q_full_only", goals=["full"]))
    await repo.upsert(
        _make_question("q_provisional_only", goals=["provisional"])
    )

    pool = BankBackedQuestionPool(bank, repo)
    await pool.refresh()

    rng = random.Random(42)
    picked = pool.pick("provisional", rng=rng)
    assert picked is not None
    assert picked.id == "q_provisional_only"


@pytest.mark.asyncio
async def test_pick_excludes_recent_ids() -> None:
    bank = InMemoryQuestionBank()
    repo = InMemoryQuestionRepo()
    for qid in ("q1", "q2", "q3"):
        await bank.add(_make_stored(qid, status="published"))
        await repo.upsert(_make_question(qid))

    pool = BankBackedQuestionPool(bank, repo)
    await pool.refresh()

    rng = random.Random(0)
    # exclude q1, q2 → q3 のみ候補
    for _ in range(5):
        picked = pool.pick("provisional", exclude_ids={"q1", "q2"}, rng=rng)
        assert picked is not None
        assert picked.id == "q3"


@pytest.mark.asyncio
async def test_pick_falls_back_when_all_excluded() -> None:
    """Phase 1 制約: 全件除外時は除外無視で再抽選 (QuestionPool と同挙動)。"""
    bank = InMemoryQuestionBank()
    repo = InMemoryQuestionRepo()
    await bank.add(_make_stored("q1", status="published"))
    await repo.upsert(_make_question("q1"))

    pool = BankBackedQuestionPool(bank, repo)
    await pool.refresh()
    picked = pool.pick("provisional", exclude_ids={"q1"})
    assert picked is not None
    assert picked.id == "q1"


@pytest.mark.asyncio
async def test_pick_returns_none_when_pool_empty() -> None:
    pool = BankBackedQuestionPool(InMemoryQuestionBank(), InMemoryQuestionRepo())
    await pool.refresh()
    assert pool.pick("provisional") is None
    assert len(pool) == 0


@pytest.mark.asyncio
async def test_satisfies_question_pool_like_protocol() -> None:
    pool = BankBackedQuestionPool(InMemoryQuestionBank(), InMemoryQuestionRepo())
    assert isinstance(pool, QuestionPoolLike)
