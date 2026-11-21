"""アプリ依存の組み立て（DI）。

`storage_mode` に応じて `RosterRepo` 実装を選び、`RosterService` と OCR エンジンを
構築する。CSV の「プレビュー → 確定」を跨ぐため、ユーザー単位の保留インポートを
プロセス内に保持する（単一インスタンス・低頻度の夫婦利用を前提）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings
from app.models import EntryDraft
from app.repositories.in_memory import InMemoryRosterRepo
from app.repositories.protocols import RosterRepo
from app.services.ocr import OcrEngine, build_ocr_engine
from app.services.roster import RosterService


def build_repo(settings: Settings) -> RosterRepo:
    """設定に応じた名簿リポジトリを構築する。"""
    if settings.storage_mode == "sheets":
        from app.repositories.sheets import SheetsRosterRepo

        return SheetsRosterRepo.from_settings(
            spreadsheet_id=settings.spreadsheet_id,
            worksheet_name=settings.worksheet_name,
            credentials_path=settings.google_credentials_path,
        )
    return InMemoryRosterRepo()


@dataclass
class AppDeps:
    """route から参照するアプリ依存一式。"""

    settings: Settings
    roster: RosterService
    ocr_engine: OcrEngine
    # user_id → CSV プレビュー済みの登録候補。確定時に取り出す。
    pending_imports: dict[str, list[EntryDraft]] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: Settings) -> AppDeps:
        repo = build_repo(settings)
        return cls(
            settings=settings,
            roster=RosterService(repo),
            ocr_engine=build_ocr_engine(settings.ocr_provider),
        )


__all__ = ["AppDeps", "build_repo"]
