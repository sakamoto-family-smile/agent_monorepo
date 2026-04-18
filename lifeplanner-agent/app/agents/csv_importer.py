"""
Money Forward ME の CSV エクスポートをパースして Transaction のリストへ変換する。

実 MF CSV（CP932）の列:
  "計算対象","日付","内容","金額（円）","保有金融機関","大項目","中項目","メモ","振替","ID"

設計方針:
  - 行単位の失敗はログして継続（ImportResult の `skipped_invalid` に計上）
  - DB はこの層では触らない。永続化は呼び出し側の責務
  - エンコーディングは utils/encoding で自動判定
  - 金額は Decimal で保持（float は使わない）
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from io import StringIO
from pathlib import Path

from models.transaction import ImportResult, Transaction
from services.category_mapper import CategoryMapper, load_category_mapper
from utils.encoding import detect_encoding
from utils.money import to_yen

logger = logging.getLogger(__name__)

# MF CSV の想定列名（ヘッダで検証する）
_REQUIRED_COLUMNS: tuple[str, ...] = (
    "計算対象",
    "日付",
    "内容",
    "金額（円）",
    "保有金融機関",
    "大項目",
    "中項目",
    "メモ",
    "振替",
    "ID",
)


def _parse_date(raw: str) -> datetime.date:
    """MF の日付は 'YYYY/MM/DD' が既定。ダブルクオート剥離済み前提。"""
    return datetime.strptime(raw.strip(), "%Y/%m/%d").date()


def _parse_bool_flag(raw: str) -> bool:
    """'0' / '1' のフラグを bool 化。空は False。"""
    v = raw.strip().strip('"')
    return v == "1"


def parse_bytes(
    raw: bytes,
    *,
    source_label: str = "<memory>",
    include_transfers: bool = False,
    include_excluded: bool = False,
    mapper: CategoryMapper | None = None,
) -> ImportResult:
    """
    CSV バイト列をパースして ImportResult を返す。

    include_transfers: True なら振替も transactions に含める
    include_excluded:  True なら計算対象外(計算対象=0)も transactions に含める
    """
    encoding = detect_encoding(raw)
    text = raw.decode(encoding, errors="replace")
    return _parse_text(
        text,
        source_label=source_label,
        encoding=encoding,
        include_transfers=include_transfers,
        include_excluded=include_excluded,
        mapper=mapper or load_category_mapper(),
    )


def parse_file(
    path: str | Path,
    *,
    include_transfers: bool = False,
    include_excluded: bool = False,
    mapper: CategoryMapper | None = None,
) -> ImportResult:
    """ファイルパスから ImportResult を得る薄いラッパー。"""
    p = Path(path)
    return parse_bytes(
        p.read_bytes(),
        source_label=str(p),
        include_transfers=include_transfers,
        include_excluded=include_excluded,
        mapper=mapper,
    )


def _parse_text(
    text: str,
    *,
    source_label: str,
    encoding: str,
    include_transfers: bool,
    include_excluded: bool,
    mapper: CategoryMapper,
) -> ImportResult:
    reader = csv.DictReader(StringIO(text))

    header = reader.fieldnames or []
    missing = [c for c in _REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ValueError(
            f"MF CSV header mismatch: missing columns {missing}. "
            f"Got header={header}"
        )

    transactions: list[Transaction] = []
    skipped_transfer = 0
    skipped_excluded = 0
    skipped_invalid = 0
    total_rows = 0
    seen_ids: set[str] = set()
    duplicates_in_file = 0

    for row in reader:
        total_rows += 1

        try:
            source_id = (row.get("ID") or "").strip()
            is_transfer = _parse_bool_flag(row.get("振替", "0"))
            is_target = _parse_bool_flag(row.get("計算対象", "1"))

            if is_transfer and not include_transfers:
                skipped_transfer += 1
                continue

            if not is_target and not include_excluded:
                skipped_excluded += 1
                continue

            mf_category = (row.get("大項目") or "").strip()
            canonical = mapper.resolve(mf_category)
            tx = Transaction(
                source_id=source_id,
                date=_parse_date(row["日付"]),
                content=(row.get("内容") or "").strip(),
                amount=to_yen(row.get("金額（円）", "0")),
                account=(row.get("保有金融機関") or "").strip(),
                category=mf_category,
                subcategory=(row.get("中項目") or "").strip() or None,
                canonical_category=canonical.canonical,
                expense_type=canonical.expense_type,
                memo=(row.get("メモ") or "").strip() or None,
                is_transfer=is_transfer,
                is_target=is_target,
            )

            if source_id and source_id in seen_ids:
                duplicates_in_file += 1
                continue
            if source_id:
                seen_ids.add(source_id)

            transactions.append(tx)

        except Exception as e:  # noqa: BLE001 — 行単位フェイルトレラント
            skipped_invalid += 1
            logger.warning(
                "Skipping invalid MF row at line %d in %s: %s",
                total_rows + 1,
                source_label,
                e,
            )

    return ImportResult(
        source_file=source_label,
        encoding=encoding,
        total_rows=total_rows,
        imported=len(transactions),
        skipped_transfer=skipped_transfer,
        skipped_excluded=skipped_excluded,
        skipped_invalid=skipped_invalid,
        duplicates_in_file=duplicates_in_file,
        transactions=transactions,
    )
