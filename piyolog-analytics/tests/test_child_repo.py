"""Phase 4-B: ChildRepo の CRUD + 入力バリデーション。"""

from __future__ import annotations

import pathlib
import tempfile

import pytest
from repositories.child_repo import (
    ChildRepo,
    is_valid_birth_date,
    is_valid_name,
)
from repositories.event_repo import EventRepo


@pytest.fixture
async def child_repo():
    with tempfile.TemporaryDirectory() as td:
        db_path = pathlib.Path(td) / "test.db"
        ev = EventRepo(database_url=f"sqlite+aiosqlite:///{db_path}")
        await ev.initialize()
        cr = ChildRepo(engine=ev.engine)
        yield cr
        await ev.dispose()


# ---- バリデーション ----


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2025-08-15", True),
        ("2026-12-31", True),
        ("2025-13-01", False),  # 月レンジ外
        ("2025-02-30", False),  # 存在しない日
        ("25-08-15", False),  # 桁不足
        ("", False),
        ("2025/08/15", False),
        ("2025-8-15", False),
    ],
)
def test_is_valid_birth_date(value: str, expected: bool) -> None:
    assert is_valid_birth_date(value) is expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("たろう", True),
        ("Taro", True),
        ("a" * 32, True),
        ("a" * 33, False),
        ("", False),
        ("name\nwith\nnewline", False),
        ("name\twith\ttab", False),
    ],
)
def test_is_valid_name(value: str, expected: bool) -> None:
    assert is_valid_name(value) is expected


# ---- repo CRUD ----


@pytest.mark.asyncio
async def test_get_returns_none_when_not_set(child_repo: ChildRepo) -> None:
    child = await child_repo.get(family_id="f1", child_id="default")
    assert child is None


@pytest.mark.asyncio
async def test_upsert_birth_date_creates_row(child_repo: ChildRepo) -> None:
    child = await child_repo.upsert_birth_date(
        family_id="f1", child_id="default", birth_date="2025-08-15"
    )
    assert child.family_id == "f1"
    assert child.child_id == "default"
    assert child.birth_date == "2025-08-15"
    assert child.name is None
    fetched = await child_repo.get(family_id="f1", child_id="default")
    assert fetched is not None
    assert fetched.birth_date == "2025-08-15"


@pytest.mark.asyncio
async def test_upsert_birth_date_then_name_keeps_birth_date(
    child_repo: ChildRepo,
) -> None:
    """name を後から入れても birth_date は保持される (column 単位の upsert)。"""
    await child_repo.upsert_birth_date(
        family_id="f1", child_id="default", birth_date="2025-08-15"
    )
    await child_repo.upsert_name(family_id="f1", child_id="default", name="たろう")
    fetched = await child_repo.get(family_id="f1", child_id="default")
    assert fetched is not None
    assert fetched.birth_date == "2025-08-15"
    assert fetched.name == "たろう"


@pytest.mark.asyncio
async def test_upsert_birth_date_overwrites(child_repo: ChildRepo) -> None:
    await child_repo.upsert_birth_date(
        family_id="f1", child_id="default", birth_date="2025-08-15"
    )
    await child_repo.upsert_birth_date(
        family_id="f1", child_id="default", birth_date="2026-01-01"
    )
    fetched = await child_repo.get(family_id="f1", child_id="default")
    assert fetched is not None
    assert fetched.birth_date == "2026-01-01"


@pytest.mark.asyncio
async def test_upsert_birth_date_rejects_invalid(child_repo: ChildRepo) -> None:
    with pytest.raises(ValueError):
        await child_repo.upsert_birth_date(
            family_id="f1", child_id="default", birth_date="invalid"
        )


@pytest.mark.asyncio
async def test_upsert_name_rejects_invalid(child_repo: ChildRepo) -> None:
    with pytest.raises(ValueError):
        await child_repo.upsert_name(
            family_id="f1", child_id="default", name="x" * 33
        )


@pytest.mark.asyncio
async def test_separate_families_isolated(child_repo: ChildRepo) -> None:
    """family_id が異なれば独立にレコードが立つ (将来の複数家族対応)。"""
    await child_repo.upsert_birth_date(
        family_id="fA", child_id="default", birth_date="2025-08-15"
    )
    await child_repo.upsert_birth_date(
        family_id="fB", child_id="default", birth_date="2024-04-01"
    )
    a = await child_repo.get(family_id="fA", child_id="default")
    b = await child_repo.get(family_id="fB", child_id="default")
    assert a is not None and a.birth_date == "2025-08-15"
    assert b is not None and b.birth_date == "2024-04-01"
