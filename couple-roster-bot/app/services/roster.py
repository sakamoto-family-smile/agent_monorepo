"""名簿の業務ロジック（登録 / 検索 / 更新 / 削除）。

`RosterRepo` に依存し、検証・重複チェック・ID / タイムスタンプ付与を担う。
`id_factory` / `clock` を注入できるようにしてテストで決定的にする。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from app.models import (
    EntryDraft,
    RosterEntry,
    dedup_key,
)
from app.repositories.protocols import RosterRepo


class DuplicateEntryError(ValueError):
    """氏名＋住所が既存レコードと重複している。"""


def _default_id() -> str:
    return str(uuid.uuid4())


def _default_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RosterService:
    """名簿の CRUD と検索を提供するサービス。"""

    def __init__(
        self,
        repo: RosterRepo,
        *,
        id_factory: Callable[[], str] = _default_id,
        clock: Callable[[], str] = _default_now,
    ) -> None:
        self._repo = repo
        self._new_id = id_factory
        self._now = clock

    def list_all(self) -> list[RosterEntry]:
        return self._repo.list_all()

    def get(self, entry_id: str) -> RosterEntry | None:
        return self._repo.get(entry_id)

    def register(self, draft: EntryDraft, *, created_by: str = "") -> RosterEntry:
        """下書きを検証し、重複がなければ 1 件登録して返す。"""
        relation = draft.validate_draft()
        normalized = draft.normalized()
        if self._find_duplicate(normalized.name, normalized.address) is not None:
            raise DuplicateEntryError(
                f"すでに登録されています: {normalized.name} / {normalized.address}"
            )
        now = self._now()
        entry = RosterEntry(
            id=self._new_id(),
            name=normalized.name,
            kana=normalized.kana,
            zip=normalized.zip,
            address=normalized.address,
            relation=relation,
            note=normalized.note,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        self._repo.add(entry)
        return entry

    def update(self, entry_id: str, draft: EntryDraft) -> RosterEntry | None:
        """既存レコードを下書きの内容で更新する。対象がなければ None。"""
        existing = self._repo.get(entry_id)
        if existing is None:
            return None
        relation = draft.validate_draft()
        normalized = draft.normalized()
        updated = existing.with_updates(
            name=normalized.name,
            kana=normalized.kana,
            zip=normalized.zip,
            address=normalized.address,
            relation=relation,
            note=normalized.note,
            updated_at=self._now(),
        )
        self._repo.update(updated)
        return updated

    def delete(self, entry_id: str) -> bool:
        return self._repo.delete(entry_id)

    def import_drafts(
        self, drafts: list[EntryDraft], *, created_by: str = ""
    ) -> list[RosterEntry]:
        """検証済みの下書き群をまとめて登録する（CSV インポートの確定）。

        重複除去は `csv_import.prepare_import` 側で済んでいる前提。ここでは
        ID / タイムスタンプを付与して一括追記する。
        """
        entries: list[RosterEntry] = []
        for draft in drafts:
            relation = draft.validate_draft()
            normalized = draft.normalized()
            now = self._now()
            entries.append(
                RosterEntry(
                    id=self._new_id(),
                    name=normalized.name,
                    kana=normalized.kana,
                    zip=normalized.zip,
                    address=normalized.address,
                    relation=relation,
                    note=normalized.note,
                    created_by=created_by,
                    created_at=now,
                    updated_at=now,
                )
            )
        if entries:
            self._repo.add_many(entries)
        return entries

    def search(self, query: str) -> list[RosterEntry]:
        """氏名・ふりがな・間柄・住所を対象にした部分一致検索。"""
        needle = (query or "").strip()
        if not needle:
            return self._repo.list_all()
        results = []
        for entry in self._repo.list_all():
            haystack = " ".join(
                [entry.name, entry.kana, entry.relation.value, entry.address]
            )
            if needle in haystack:
                results.append(entry)
        return results

    def _find_duplicate(self, name: str, address: str) -> RosterEntry | None:
        target = dedup_key(name, address)
        for entry in self._repo.list_all():
            if dedup_key(entry.name, entry.address) == target:
                return entry
        return None


__all__ = ["DuplicateEntryError", "RosterService"]
