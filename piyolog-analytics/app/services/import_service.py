"""ぴよログ .txt 取り込みの一連の流れを束ねる。

  txt bytes → decode → parse → repo.import_events
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from models.piyolog import ParseResult
from parser.piyolog_parser import parse_piyolog_text
from repositories.event_repo import DuplicateImportError, EventRepo, ImportBatch

logger = logging.getLogger(__name__)


class InvalidPiyologFileError(Exception):
    """入力 bytes がピヨログ .txt として妥当でない場合。"""


@dataclass(frozen=True)
class ImportOutcome:
    batch: ImportBatch
    parse_result: ParseResult


def _decode(data: bytes) -> str:
    """UTF-8 / Shift_JIS 両対応のゆるいデコード。"""
    for enc in ("utf-8", "utf-8-sig", "cp932", "shift_jis"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise InvalidPiyologFileError("failed to decode bytes as text")


def _validate_header(text: str) -> None:
    if "【ぴよログ】" not in text:
        raise InvalidPiyologFileError(
            "missing ぴよログ header; file does not look like a piyolog export"
        )


async def import_piyolog_bytes(
    *,
    repo: EventRepo,
    family_id: str,
    source_user_id: str,
    child_id: str,
    data: bytes,
    source_filename: str | None,
    max_bytes: int,
) -> ImportOutcome:
    """bytes を取り込んで永続化する。

    - サイズ超過 → InvalidPiyologFileError
    - ヘッダ欠落 → InvalidPiyologFileError
    - 同一 raw 重複 → DuplicateImportError (呼び出し側で捕捉して UX 対応)
    """
    if len(data) > max_bytes:
        raise InvalidPiyologFileError(
            f"file too large: {len(data)} bytes > {max_bytes} bytes"
        )

    text = _decode(data)
    _validate_header(text)
    parse_result = parse_piyolog_text(text)
    events = [e for day in parse_result.days for e in day.events]

    batch = await repo.import_events(
        family_id=family_id,
        source_user_id=source_user_id,
        child_id=child_id,
        raw_text=text,
        source_filename=source_filename,
        events=events,
    )
    return ImportOutcome(batch=batch, parse_result=parse_result)


__all__ = [
    "DuplicateImportError",
    "ImportOutcome",
    "InvalidPiyologFileError",
    "import_piyolog_bytes",
]
