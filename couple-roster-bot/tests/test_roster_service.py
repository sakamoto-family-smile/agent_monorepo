"""RosterService の単体テスト（in-memory リポジトリを使用）。"""

from __future__ import annotations

import itertools

import pytest

from app.models import EntryDraft, EntryValidationError
from app.repositories.in_memory import InMemoryRosterRepo
from app.services.roster import DuplicateEntryError, RosterService


def _service() -> RosterService:
    """ID / 時刻を固定化した決定的なサービス。"""
    counter = itertools.count(1)
    return RosterService(
        InMemoryRosterRepo(),
        id_factory=lambda: f"id-{next(counter)}",
        clock=lambda: "2026-08-01T00:00:00+00:00",
    )


def _draft(name: str = "山田太郎", address: str = "東京都港区", relation: str = "父") -> EntryDraft:
    return EntryDraft(name=name, address=address, relation=relation)


class TestRegister:
    def test_registers_and_assigns_id_and_timestamps(self) -> None:
        svc = _service()
        entry = svc.register(_draft(), created_by="夫")
        assert entry.id == "id-1"
        assert entry.created_by == "夫"
        assert entry.created_at == "2026-08-01T00:00:00+00:00"
        assert svc.list_all() == [entry]

    def test_rejects_invalid_draft(self) -> None:
        svc = _service()
        with pytest.raises(EntryValidationError):
            svc.register(_draft(relation="ペット"))

    def test_rejects_duplicate(self) -> None:
        svc = _service()
        svc.register(_draft())
        with pytest.raises(DuplicateEntryError):
            svc.register(_draft(name="山田 太郎", address="東京都 港区"))


class TestSearch:
    def test_matches_by_name(self) -> None:
        svc = _service()
        svc.register(_draft(name="山田太郎"))
        svc.register(_draft(name="鈴木花子", address="大阪市"))
        assert [e.name for e in svc.search("山田")] == ["山田太郎"]

    def test_matches_by_relation(self) -> None:
        svc = _service()
        svc.register(_draft(name="山田", relation="父"))
        svc.register(_draft(name="鈴木", address="大阪", relation="友人・知人"))
        assert [e.name for e in svc.search("友人")] == ["鈴木"]

    def test_empty_query_returns_all(self) -> None:
        svc = _service()
        svc.register(_draft())
        assert len(svc.search("")) == 1


class TestUpdateDelete:
    def test_update_changes_fields_and_bumps_updated_at(self) -> None:
        svc = _service()
        entry = svc.register(_draft())
        updated = svc.update(entry.id, _draft(name="山田次郎"))
        assert updated is not None
        assert updated.name == "山田次郎"
        assert updated.id == entry.id

    def test_update_missing_returns_none(self) -> None:
        svc = _service()
        assert svc.update("nope", _draft()) is None

    def test_delete(self) -> None:
        svc = _service()
        entry = svc.register(_draft())
        assert svc.delete(entry.id) is True
        assert svc.list_all() == []

    def test_delete_missing_returns_false(self) -> None:
        assert _service().delete("nope") is False


class TestImportDrafts:
    def test_bulk_adds_with_ids(self) -> None:
        svc = _service()
        created = svc.import_drafts(
            [_draft(name="A", address="a"), _draft(name="B", address="b")],
            created_by="妻",
        )
        assert [e.id for e in created] == ["id-1", "id-2"]
        assert len(svc.list_all()) == 2
        assert all(e.created_by == "妻" for e in created)

    def test_empty_list_is_noop(self) -> None:
        svc = _service()
        assert svc.import_drafts([]) == []
        assert svc.list_all() == []
