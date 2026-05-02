"""Phase 1.5: 取り消し / undo コマンド振り分け検証。

EventRepo は monkeypatch で rollback_latest_batch を stub し、
command_router の挙動だけを切り出して検証する。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from models.piyolog import ImportBatch

JST = timezone(timedelta(hours=9), "Asia/Tokyo")


class _FakeRepo:
    def __init__(self, batch: ImportBatch | None) -> None:
        self.batch = batch
        self.calls: list[str] = []

    async def rollback_latest_batch(self, *, family_id: str) -> ImportBatch | None:
        self.calls.append(family_id)
        return self.batch


def _batch(filename: str | None = "day1.txt", count: int = 12) -> ImportBatch:
    return ImportBatch(
        batch_id="b" + "0" * 31,
        family_id="f1",
        source_user_id="U1",
        source_filename=filename,
        raw_text_hash="h" * 16,
        event_count=count,
        imported_at="2026-05-01T03:30:00+00:00",
        rolled_back_at="2026-05-03T05:00:00+00:00",
    )


@pytest.mark.parametrize("cmd", ["取り消し", "取消", "undo", "UNDO", "rollback"])
async def test_undo_command_calls_rollback(cmd: str) -> None:
    from services.command_router import handle_text_command

    repo = _FakeRepo(_batch())
    result = await handle_text_command(cmd, repo=repo, family_id="f1", now=datetime.now(JST))
    assert repo.calls == ["f1"]
    assert "取り消しました" in result.reply
    assert "day1.txt" in result.reply
    assert "12 件" in result.reply
    assert result.image_png is None


async def test_undo_command_no_active_batch_returns_hint() -> None:
    from services.command_router import UNDO_NO_BATCH_HINT, handle_text_command

    repo = _FakeRepo(None)
    result = await handle_text_command("取り消し", repo=repo, family_id="f1", now=datetime.now(JST))
    assert result.reply == UNDO_NO_BATCH_HINT


async def test_help_text_includes_undo() -> None:
    """HELP_TEXT に取り消しコマンドの行が含まれていること。"""
    from services.command_router import HELP_TEXT

    assert "取り消し" in HELP_TEXT
    assert "undo" in HELP_TEXT


async def test_undo_with_no_filename() -> None:
    """source_filename が None でも crash しない (placeholder で表示)。"""
    from services.command_router import handle_text_command

    repo = _FakeRepo(_batch(filename=None, count=5))
    result = await handle_text_command("undo", repo=repo, family_id="f1", now=datetime.now(JST))
    assert "(no name)" in result.reply
    assert "5 件" in result.reply
