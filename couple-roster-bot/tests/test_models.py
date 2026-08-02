"""RosterEntry / Relation / EntryDraft の単体テスト。"""

from __future__ import annotations

import pytest

from app.models import (
    FIELD_ORDER,
    EntryDraft,
    EntryValidationError,
    Relation,
    RosterEntry,
    dedup_key,
)


class TestRelation:
    def test_choices_are_in_declaration_order(self) -> None:
        # Arrange / Act
        choices = Relation.choices()
        # Assert
        assert choices[0] == "父"
        assert "友人・知人" in choices
        assert choices[-1] == "その他"

    def test_from_label_resolves_known_value(self) -> None:
        assert Relation.from_label("親戚") is Relation.RELATIVE

    def test_from_label_trims_whitespace(self) -> None:
        assert Relation.from_label("  母 ") is Relation.MOTHER

    def test_from_label_returns_none_for_unknown(self) -> None:
        assert Relation.from_label("いとこ") is None


class TestRosterEntry:
    def _entry(self) -> RosterEntry:
        return RosterEntry(
            id="id-1", name="山田太郎", address="東京都…", relation=Relation.FATHER
        )

    def test_is_frozen(self) -> None:
        entry = self._entry()
        with pytest.raises(Exception):
            entry.name = "別名"  # type: ignore[misc]

    def test_with_updates_returns_new_instance(self) -> None:
        entry = self._entry()
        updated = entry.with_updates(note="メモ")
        assert updated.note == "メモ"
        assert entry.note == ""  # 元は不変
        assert updated is not entry

    def test_to_row_matches_field_order(self) -> None:
        entry = self._entry().with_updates(kana="やまだ", zip="100-0001")
        row = entry.to_row()
        assert len(row) == len(FIELD_ORDER)
        assert row[FIELD_ORDER.index("name")] == "山田太郎"
        assert row[FIELD_ORDER.index("relation")] == "父"

    def test_from_row_roundtrip(self) -> None:
        entry = self._entry().with_updates(kana="やまだ", note="x")
        row_dict = dict(zip(FIELD_ORDER, entry.to_row(), strict=True))
        restored = RosterEntry.from_row(row_dict)
        assert restored == entry

    def test_from_row_unknown_relation_falls_back_to_other(self) -> None:
        restored = RosterEntry.from_row(
            {"id": "x", "name": "n", "address": "a", "relation": "謎"}
        )
        assert restored.relation is Relation.OTHER


class TestEntryDraftValidation:
    def test_valid_draft_returns_relation(self) -> None:
        draft = EntryDraft(name="花子", address="住所", relation="母")
        assert draft.validate_draft() is Relation.MOTHER

    def test_missing_name_raises(self) -> None:
        draft = EntryDraft(name="  ", address="住所", relation="母")
        with pytest.raises(EntryValidationError, match="名前"):
            draft.validate_draft()

    def test_missing_address_raises(self) -> None:
        draft = EntryDraft(name="花子", address="", relation="母")
        with pytest.raises(EntryValidationError, match="住所"):
            draft.validate_draft()

    def test_bad_relation_raises(self) -> None:
        draft = EntryDraft(name="花子", address="住所", relation="ペット")
        with pytest.raises(EntryValidationError, match="間柄"):
            draft.validate_draft()

    def test_bad_zip_raises(self) -> None:
        draft = EntryDraft(name="花子", address="住所", relation="母", zip="12345")
        with pytest.raises(EntryValidationError, match="郵便番号"):
            draft.validate_draft()

    def test_zip_without_hyphen_is_valid(self) -> None:
        draft = EntryDraft(name="花子", address="住所", relation="母", zip="1000001")
        assert draft.validate_draft() is Relation.MOTHER


class TestDedupKey:
    def test_ignores_whitespace_differences(self) -> None:
        assert dedup_key("山田 太郎", "東京都 港区") == dedup_key("山田太郎", "東京都港区")

    def test_distinguishes_different_people(self) -> None:
        assert dedup_key("山田", "東京") != dedup_key("鈴木", "東京")
