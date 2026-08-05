"""リポジトリの Protocol 定義。

名簿データへのアクセスをこの 1 つのインターフェースに閉じ込める。
in-memory（テスト / 開発）と Google スプレッドシート（本番）が実装する。
将来 Firestore / Cloud SQL へ移行する場合もここを実装するだけでよい。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models import RosterEntry


@runtime_checkable
class RosterRepo(Protocol):
    """名簿レコードの永続化インターフェース。"""

    def list_all(self) -> list[RosterEntry]:
        """全レコードを返す。"""
        ...

    def get(self, entry_id: str) -> RosterEntry | None:
        """ID で 1 件取得。存在しなければ None。"""
        ...

    def add(self, entry: RosterEntry) -> None:
        """1 件追加する。"""
        ...

    def add_many(self, entries: list[RosterEntry]) -> None:
        """複数件をまとめて追加する（CSV インポート用）。"""
        ...

    def update(self, entry: RosterEntry) -> bool:
        """既存レコードを差し替える。対象がなければ False。"""
        ...

    def delete(self, entry_id: str) -> bool:
        """ID で 1 件削除する。対象がなければ False。"""
        ...


__all__ = ["RosterRepo"]
