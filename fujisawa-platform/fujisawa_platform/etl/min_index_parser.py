"""令和 4 年最低指数 PDF (`r4-4nyuusyonaiteisisuu.pdf`) parser。

調査ノート §A2-2 で確認した PDF 構造:
- 3 ページ・220 KB
- 120+ 施設 × age_class 0..5 の表
- 各セルは `<基礎点><優先順位><調整>` 形式 (例: `10F11`) または以下のマーカー:
  - `※`: 同点細目あり (`10F11※`)
  - `△`: 内定者 1 名 (個人情報保護で非公開)
  - `○`: 定員に空きあり
  - `-` / `−`: 空きなし
  - `＼`: クラスなし

`parse_min_index_table` は `PdfTable` (Docling 抽出) を受け取り、`MinIndexEntry` の
リストを返す。マーカーセル / 不正フォーマット / resolver で解決できない施設は skip。

最終的に `wayback_backfill` (Phase 4-2g) が `admission_results.min_*` 4 フィールドに
反映する。
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from fujisawa_platform.etl.admission_parser import parse_min_index_notation
from fujisawa_platform.pdf_pipeline import PdfTable
from fujisawa_platform.resolver import FacilityResolver, NoMatchError

_AGE_COLUMN_RE = re.compile(r"^(?P<age>[0-5])\s*歳児\s*$")
_FACILITY_NAME_CANDIDATES = ("施設名", "保育施設名", "園名")


class MinIndexEntry(BaseModel):
    """令和 4 年最低指数 PDF の 1 セルから抽出した 1 (施設, 年齢クラス) のエントリ。"""

    model_config = ConfigDict(frozen=True)

    facility_id: str
    age_class: int
    basic: int
    priority: str
    coord: int
    notation: str  # 元の表記 (例: `10F11` / `10F11※`)
    source_pdf_url: str


def parse_min_index_table(
    *,
    table: PdfTable,
    source_pdf_url: str,
    resolver: FacilityResolver,
) -> list[MinIndexEntry]:
    """令和 4 年最低指数 PDF の表 1 つを `MinIndexEntry` のリストに変換。

    施設名列 + 各 age_class カラム (`0歳児`..`5歳児`) を持つ table を想定。
    マーカーセル / 不正フォーマット / resolver 不一致の行は skip。
    """
    facility_col = _find_facility_name_column(table.headers)
    if facility_col is None:
        return []
    age_columns = _index_age_columns(table.headers)
    if not age_columns:
        return []

    entries: list[MinIndexEntry] = []
    for row in table.rows:
        if len(row) <= facility_col:
            continue
        facility_name = row[facility_col].strip()
        if not facility_name:
            continue

        try:
            hit = resolver.resolve(facility_name)
        except NoMatchError:
            continue

        for age_class, col_idx in age_columns.items():
            if col_idx >= len(row):
                continue
            cell = row[col_idx].strip()
            parsed = parse_min_index_notation(cell)
            if parsed is None:
                continue  # マーカー / 空 / 不正フォーマット
            basic, priority, coord = parsed
            entries.append(
                MinIndexEntry(
                    facility_id=hit.facility_id,
                    age_class=age_class,
                    basic=basic,
                    priority=priority,
                    coord=coord,
                    notation=cell,
                    source_pdf_url=source_pdf_url,
                )
            )
    return entries


def _find_facility_name_column(headers: list[str]) -> int | None:
    for idx, header in enumerate(headers):
        if header.strip() in _FACILITY_NAME_CANDIDATES:
            return idx
    return None


def _index_age_columns(headers: list[str]) -> dict[int, int]:
    """`{age_class: col_idx}` の対応。"""
    result: dict[int, int] = {}
    for idx, header in enumerate(headers):
        match = _AGE_COLUMN_RE.match(header.strip())
        if match is None:
            continue
        age = int(match.group("age"))
        result[age] = idx
    return result


__all__ = ["MinIndexEntry", "parse_min_index_table"]
