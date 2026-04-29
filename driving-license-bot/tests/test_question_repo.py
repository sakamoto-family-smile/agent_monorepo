"""C2: InMemoryQuestionRepo の基本動作。"""

from __future__ import annotations

import pytest

from app.models import Choice, Question, QuestionFormat, Source
from app.models.question import SourceType
from app.repositories.question_repo import InMemoryQuestionRepo


def _make(qid: str = "q_x") -> Question:
    return Question(
        id=qid,
        version=1,
        body="一時停止の標識がある場所では必ず停止する。",
        format=QuestionFormat.TRUE_FALSE,
        choices=[Choice(index=0, text="正しい"), Choice(index=1, text="誤り")],
        correct=0,
        explanation="...",
        applicable_goals=["provisional"],
        difficulty="standard",
        category="rules",
        sources=[
            Source(
                type=SourceType.LAW,
                title="道路交通法 第43条",
                url="https://elaws.e-gov.go.jp/document?lawid=335AC0000000105",
                quoted_text="...",
            )
        ],
    )


@pytest.mark.asyncio
async def test_upsert_and_get_roundtrip() -> None:
    repo = InMemoryQuestionRepo()
    q = _make("q_x")
    await repo.upsert(q)
    fetched = await repo.get("q_x")
    assert fetched is not None
    assert fetched.id == "q_x"
    assert fetched.body == q.body


@pytest.mark.asyncio
async def test_get_returns_none_for_missing() -> None:
    repo = InMemoryQuestionRepo()
    assert await repo.get("nope") is None


@pytest.mark.asyncio
async def test_upsert_overwrites_existing() -> None:
    repo = InMemoryQuestionRepo()
    q = _make("q_x")
    await repo.upsert(q)
    q2 = q.model_copy(update={"body": "新本文"})
    await repo.upsert(q2)
    fetched = await repo.get("q_x")
    assert fetched is not None
    assert fetched.body == "新本文"


@pytest.mark.asyncio
async def test_delete_removes() -> None:
    repo = InMemoryQuestionRepo()
    await repo.upsert(_make("q_x"))
    await repo.delete("q_x")
    assert await repo.get("q_x") is None


@pytest.mark.asyncio
async def test_get_returns_copy_not_shared_reference() -> None:
    """mutability 防御: 取得した instance を変更しても store に影響しない。"""
    repo = InMemoryQuestionRepo()
    await repo.upsert(_make("q_x"))
    a = await repo.get("q_x")
    a.body = "tampered"  # type: ignore[misc]  # pydantic v2 では ignore
    b = await repo.get("q_x")
    assert b.body != "tampered"
