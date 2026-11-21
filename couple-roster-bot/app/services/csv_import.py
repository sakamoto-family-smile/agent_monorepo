"""CSV 一括インポート — 解析・列マッピング・検証・重複チェック。

書き込みは行わない。検証済みの下書きと、失敗行のエラーレポートを返すだけ。
実際の登録は `RosterService.import_drafts` が担い、「プレビュー → 確定」を
分離できるようにしている。

- 文字コード: UTF-8 (BOM 可) → Shift_JIS(cp932) の順に自動判定。
- 列マッピング: 英語 / 日本語どちらのヘッダでも対応（順不同可）。
- 重複: 氏名＋住所キーで既存＋バッチ内の両方を判定。
"""

from __future__ import annotations

import csv
import io

from pydantic import BaseModel

from app.models import EntryDraft, EntryValidationError, dedup_key

# ヘッダ名 → 正規フィールド名。小文字化・前後空白除去した上で照合する。
HEADER_ALIASES: dict[str, str] = {
    "name": "name",
    "名前": "name",
    "氏名": "name",
    "kana": "kana",
    "ふりがな": "kana",
    "フリガナ": "kana",
    "zip": "zip",
    "郵便番号": "zip",
    "〒": "zip",
    "address": "address",
    "住所": "address",
    "relation": "relation",
    "間柄": "relation",
    "続柄": "relation",
    "note": "note",
    "メモ": "note",
    "備考": "note",
}

# データ行の開始行番号。1 行目はヘッダなので最初のレコードは 2 行目。
_FIRST_DATA_LINE = 2


class RowError(BaseModel):
    """インポートに失敗した行の情報。"""

    line: int
    reason: str


class ImportPreview(BaseModel):
    """インポート前のプレビュー結果。"""

    valid_drafts: list[EntryDraft] = []
    errors: list[RowError] = []
    duplicate_count: int = 0
    total_rows: int = 0

    @property
    def valid_count(self) -> int:
        return len(self.valid_drafts)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    def summary(self) -> str:
        """LINE 返信用の 1 行サマリ。"""
        return (
            f"{self.total_rows} 件中 "
            f"{self.valid_count} 件登録可 / "
            f"{self.duplicate_count} 件重複 / "
            f"{self.error_count} 件エラー"
        )


def decode_csv_bytes(data: bytes) -> str:
    """UTF-8(BOM可) → Shift_JIS の順にデコードを試みる。"""
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    # 最終手段: 不正バイトは置換して読み込む（完全失敗を避ける）。
    return data.decode("utf-8", errors="replace")


def _map_headers(fieldnames: list[str] | None) -> dict[str, str]:
    """CSV のヘッダ名 → 正規フィールド名の対応表を作る。"""
    mapping: dict[str, str] = {}
    for raw in fieldnames or []:
        key = (raw or "").strip().lstrip("﻿").lower()
        canonical = HEADER_ALIASES.get((raw or "").strip()) or HEADER_ALIASES.get(key)
        if canonical:
            mapping[raw] = canonical
    return mapping


def _row_to_draft(row: dict[str, str], header_map: dict[str, str]) -> EntryDraft:
    """1 行の dict を正規フィールドへ詰め替えて下書きにする。"""
    fields: dict[str, str] = {}
    for raw_header, value in row.items():
        canonical = header_map.get(raw_header)
        if canonical:
            fields[canonical] = (value or "").strip()
    return EntryDraft(**fields)


def prepare_import(data: bytes, existing_keys: set[str]) -> ImportPreview:
    """CSV バイト列を検証し、登録可能な下書きとエラーを返す。

    `existing_keys` は既存レコードの `dedup_key` 集合。バッチ内の重複も検出する。
    """
    text = decode_csv_bytes(data)
    reader = csv.DictReader(io.StringIO(text))
    header_map = _map_headers(reader.fieldnames)

    if "name" not in header_map.values() or "address" not in header_map.values():
        return ImportPreview(
            errors=[
                RowError(
                    line=1,
                    reason="ヘッダに『名前(name)』と『住所(address)』の列が必要です",
                )
            ]
        )

    preview = ImportPreview()
    seen_keys: set[str] = set(existing_keys)

    for offset, row in enumerate(reader):
        line = _FIRST_DATA_LINE + offset
        preview.total_rows += 1
        draft = _row_to_draft(row, header_map).normalized()

        if not any([draft.name, draft.address, draft.relation]):
            # 完全な空行はスキップ（件数にも数えない）。
            preview.total_rows -= 1
            continue

        try:
            draft.validate_draft()
        except EntryValidationError as exc:
            preview.errors.append(RowError(line=line, reason=str(exc)))
            continue

        key = dedup_key(draft.name, draft.address)
        if key in seen_keys:
            preview.duplicate_count += 1
            continue
        seen_keys.add(key)
        preview.valid_drafts.append(draft)

    return preview


__all__ = [
    "HEADER_ALIASES",
    "ImportPreview",
    "RowError",
    "decode_csv_bytes",
    "prepare_import",
]
