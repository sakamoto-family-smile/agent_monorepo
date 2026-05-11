"""4 月入所結果 PDF の表 → `AdmissionResultRecord` 変換。

PDF 構造 (proposal 0003 §A4 / 調査ノート):
- 行: 1 施設 1 行
- 列: `<施設名>` + 各 age_class 0..5 ごとに `<{N}歳児定員>` `<{N}歳児申込>` `<{N}歳児利用枠>`
- 令和 4 年 (2022) のみ別 PDF (`r4-4nyuusyonaiteisisuu.pdf`) で最低指数情報あり
  → `min_index_notation` (例: `10F11※`) を `parse_min_index_notation` で分解可能

本 parser は **通常の 1 次・2 次入所結果 PDF** を対象とし、`min_*` フィールドは None で残す。
令和 4 年バックフィル用の min_index 抽出ロジックは Phase 4-2g (`wayback_backfill`) で別途
実装するが、`parse_min_index_notation()` だけは本 PR で同梱しておく (共通 utility なので)。
"""

from __future__ import annotations

import re
from datetime import datetime

from fujisawa_platform.etl._repos.admission import AdmissionResultRecord
from fujisawa_platform.pdf_pipeline import PdfTable
from fujisawa_platform.resolver import FacilityResolver, NoMatchError

# 「0歳児定員」「2 歳児 申込」など空白揺れも吸収する正規表現。
# capture: age_class 数字 + 列種別 (定員 / 申込 / 利用枠)
_AGE_COLUMN_RE = re.compile(r"(?P<age>[0-5])\s*歳児\s*(?P<kind>定員|申込|利用枠)")

# 「10F11」「10F11※」の最低指数表記。priority は A..K (H なし、proposal §M4)。
_MIN_INDEX_RE = re.compile(
    r"^(?P<basic>\d{1,3})\s*(?P<priority>[A-GIJK])\s*(?P<coord>\d{1,3})\s*[※]?$"
)

# 単独で出現するマーカー (実数値ではないので min_* は None 扱い)
_NON_INDEX_MARKERS = frozenset({"△", "○", "〇", "-", "−", "＼", "\\"})

_FACILITY_NAME_CANDIDATES = ("施設名", "保育施設名", "園名")


def parse_admission_table(
    *,
    table: PdfTable,
    year: int,
    round: str,
    source_pdf_url: str,
    as_of: datetime,
    resolver: FacilityResolver,
) -> list[AdmissionResultRecord]:
    """1 つの `PdfTable` から `AdmissionResultRecord` のリストを返す。

    Args:
        table: Docling が抽出した 1 つの表。
        year / round: PDF が示す年度・1 次/2 次 (env 経由で渡される想定)。
        source_pdf_url: 取得元 PDF URL。
        as_of: 取得時刻 (鮮度メタ用)。
        resolver: 表記ゆれ吸収 (facilities マスタから build_facility_resolver で構築)。

    Returns:
        1 施設 × 1 age_class につき 1 件。resolver で施設不一致 / age_class 列欠落
        の行は skip される。
    """
    facility_col = _find_facility_name_column(table.headers)
    if facility_col is None:
        return []
    age_columns = _index_age_columns(table.headers)
    if not age_columns:
        return []

    records: list[AdmissionResultRecord] = []
    for row in table.rows:
        if len(row) <= facility_col:
            continue
        facility_name = row[facility_col].strip()
        if not facility_name:
            continue

        try:
            hit = resolver.resolve(facility_name)
        except NoMatchError:
            # 表記ゆれ吸収できない施設は skip (誤った facility_id への upsert を避ける)
            continue

        for age_class, cols in age_columns.items():
            capacity = _read_int(row, cols.get("定員"))
            applicants = _read_int(row, cols.get("申込"))
            vacancy = _read_int(row, cols.get("利用枠"))
            # 3 値すべて欠落 (該当 age_class なし) なら skip
            if capacity is None and applicants is None and vacancy is None:
                continue
            records.append(
                AdmissionResultRecord(
                    facility_id=hit.facility_id,
                    year=year,
                    round=round,
                    age_class=age_class,
                    applicants_at_deadline=applicants,
                    capacity=capacity,
                    vacancy_after=vacancy,
                    source_pdf_url=source_pdf_url,
                    as_of=as_of,
                )
            )
    return records


def parse_min_index_notation(notation: str) -> tuple[int, str, int] | None:
    """令和 4 年最低指数表記 (`10F11` / `10F11※`) を (basic, priority, coord) に分解。

    マーカー (`△` / `○` / `-` / `＼`) や空文字、フォーマット不一致は None。
    Phase 4-2g (`wayback_backfill`) で `r4-4nyuusyonaiteisisuu.pdf` 解析に使う想定。
    """
    if not notation:
        return None
    stripped = notation.strip()
    if not stripped or stripped in _NON_INDEX_MARKERS:
        return None
    match = _MIN_INDEX_RE.match(stripped)
    if match is None:
        return None
    return (
        int(match.group("basic")),
        match.group("priority"),
        int(match.group("coord")),
    )


def _find_facility_name_column(headers: list[str]) -> int | None:
    for idx, header in enumerate(headers):
        h = header.strip()
        if h in _FACILITY_NAME_CANDIDATES:
            return idx
    return None


def _index_age_columns(headers: list[str]) -> dict[int, dict[str, int]]:
    """ヘッダから `{age_class: {"定員": idx, "申込": idx, "利用枠": idx}}` を構築。"""
    result: dict[int, dict[str, int]] = {}
    for idx, header in enumerate(headers):
        match = _AGE_COLUMN_RE.search(header)
        if match is None:
            continue
        age = int(match.group("age"))
        kind = match.group("kind")
        result.setdefault(age, {})[kind] = idx
    return result


def _read_int(row: list[str], col_idx: int | None) -> int | None:
    if col_idx is None or col_idx >= len(row):
        return None
    cell = row[col_idx].strip()
    if not cell:
        return None
    try:
        return int(cell.replace(",", ""))
    except ValueError:
        return None


__all__ = ["parse_admission_table", "parse_min_index_notation"]
