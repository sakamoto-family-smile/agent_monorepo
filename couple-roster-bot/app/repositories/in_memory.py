"""in-memory な `RosterRepo` 実装（テスト / ローカル開発用）。

イミュータブルな `RosterEntry` を辞書で保持する。プロセス終了で消える。
"""

from __future__ import annotations

from app.models import RosterEntry


class InMemoryRosterRepo:
    """辞書ベースの名簿リポジトリ。挿入順を保持する。"""

    def __init__(self, entries: list[RosterEntry] | None = None) -> None:
        self._store: dict[str, RosterEntry] = {}
        for entry in entries or []:
            self._store[entry.id] = entry

    def list_all(self) -> list[RosterEntry]:
        return list(self._store.values())

    def get(self, entry_id: str) -> RosterEntry | None:
        return self._store.get(entry_id)

    def add(self, entry: RosterEntry) -> None:
        self._store[entry.id] = entry

    def add_many(self, entries: list[RosterEntry]) -> None:
        for entry in entries:
            self._store[entry.id] = entry

    def update(self, entry: RosterEntry) -> bool:
        if entry.id not in self._store:
            return False
        self._store[entry.id] = entry
        return True

    def delete(self, entry_id: str) -> bool:
        return self._store.pop(entry_id, None) is not None


__all__ = ["InMemoryRosterRepo"]
