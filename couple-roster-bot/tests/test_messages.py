"""返信テキスト整形（messages）の単体テスト。"""

from __future__ import annotations

from app.models import EntryDraft, Relation, RosterEntry
from app.services.messages import (
    build_register_url,
    format_entry_line,
    format_search_results,
)


def _entry(name: str = "山田太郎", **kw: str) -> RosterEntry:
    base = dict(id="x", name=name, address="東京都港区", relation=Relation.FATHER)
    base.update(kw)
    return RosterEntry(**base)  # type: ignore[arg-type]


class TestFormatEntry:
    def test_includes_name_and_relation(self) -> None:
        line = format_entry_line(_entry())
        assert "山田太郎" in line and "父" in line

    def test_includes_zip_and_note_when_present(self) -> None:
        line = format_entry_line(_entry(zip="100-0001", note="携帯あり"))
        assert "〒100-0001" in line
        assert "携帯あり" in line


class TestFormatSearchResults:
    def test_no_results_message(self) -> None:
        assert "ありませんでした" in format_search_results([], "山田")

    def test_lists_entries_with_count(self) -> None:
        out = format_search_results([_entry(), _entry(name="鈴木")], "検索")
        assert "2 件" in out
        assert "山田太郎" in out and "鈴木" in out

    def test_caps_at_max_results(self) -> None:
        entries = [_entry(name=f"人{i}") for i in range(25)]
        out = format_search_results(entries, "全件")
        assert "先頭 20 件" in out


class TestBuildRegisterUrl:
    def test_empty_base_returns_empty(self) -> None:
        assert build_register_url("") == ""

    def test_plain_url(self) -> None:
        assert build_register_url("https://x.run.app/") == "https://x.run.app/liff"

    def test_prefill_is_encoded_in_query(self) -> None:
        draft = EntryDraft(name="山田太郎", zip="100-0001")
        url = build_register_url("https://x.run.app", prefill=draft)
        assert url.startswith("https://x.run.app/liff?")
        assert "name=" in url and "zip=" in url
        # 空フィールドはクエリに含めない
        assert "address=" not in url
