"""月次空き状況 / 申込状況 PDF の表 → snapshot record 変換。

PDF 構造 (proposal 0003 §4.5.4 / 調査ノート):

  空き状況 PDF:
    - 列: <施設名> + <0歳児> <1歳児> ... <5歳児> (各セルが空き数)
  申込状況 PDF:
    - 列: <施設名> + 各 age_class ごとに <{N}歳児定員> <{N}歳児申込>

`admission_parser` と類似だが、PK が (facility_id, year_month, age_class) で
year_month を引数で渡す点が違う。
"""

from __future__ import annotations

import re
from datetime import date, datetime

from fujisawa_platform.etl._repos.vacancy import (
    ApplicationSnapshotRecord,
    VacancySnapshotRecord,
)
from fujisawa_platform.pdf_pipeline import PdfTable
from fujisawa_platform.resolver import FacilityResolver, NoMatchError

# 「0歳児」「2 歳児」など空白揺れも吸収する。空き状況 PDF はクラス名のみ。
_VACANCY_COLUMN_RE = re.compile(r"^(?P<age>[0-5])\s*歳児\s*$")
# 「0歳児定員」「0歳児申込」など、申込状況 PDF は kind 付き。
_APPLICATION_COLUMN_RE = re.compile(r"(?P<age>[0-5])\s*歳児\s*(?P<kind>定員|申込)")

_FACILITY_NAME_CANDIDATES = ("施設名", "保育施設名", "園名")


def parse_vacancy_table(
    *,
    table: PdfTable,
    year_month: str,
    snapshot_date: date,
    source_pdf_url: str,
    fetched_at: datetime,
    resolver: FacilityResolver,
) -> list[VacancySnapshotRecord]:
    """空き状況 PDF の 1 `PdfTable` を `VacancySnapshotRecord` のリストに変換。

    施設名 + 各 age_class カラム (0歳児..5歳児) を持つ table を想定。
    数値以外 / 負数のセルは skip、resolver で施設不一致の行も skip。
    """
    facility_col = _find_facility_name_column(table.headers)
    if facility_col is None:
        return []
    age_columns = _index_vacancy_columns(table.headers)
    if not age_columns:
        return []

    records: list[VacancySnapshotRecord] = []
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
            vacancies = _read_non_negative_int(row, col_idx)
            if vacancies is None:
                continue
            records.append(
                VacancySnapshotRecord(
                    facility_id=hit.facility_id,
                    year_month=year_month,
                    age_class=age_class,
                    vacancies=vacancies,
                    snapshot_date=snapshot_date,
                    source_pdf_url=source_pdf_url,
                    fetched_at=fetched_at,
                )
            )
    return records


def parse_application_table(
    *,
    table: PdfTable,
    year_month: str,
    snapshot_date: date,
    source_pdf_url: str,
    fetched_at: datetime,
    resolver: FacilityResolver,
) -> list[ApplicationSnapshotRecord]:
    """申込状況 PDF の 1 `PdfTable` を `ApplicationSnapshotRecord` のリストに変換。

    施設名 + 各 age_class について `<N歳児定員>` と `<N歳児申込>` の 2 カラムを想定。
    どちらか欠落した age_class は skip。
    """
    facility_col = _find_facility_name_column(table.headers)
    if facility_col is None:
        return []
    age_columns = _index_application_columns(table.headers)
    if not age_columns:
        return []

    records: list[ApplicationSnapshotRecord] = []
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

        for age_class, cols in age_columns.items():
            capacity = _read_non_negative_int(row, cols.get("定員"))
            applicants = _read_non_negative_int(row, cols.get("申込"))
            if capacity is None or applicants is None:
                continue
            records.append(
                ApplicationSnapshotRecord(
                    facility_id=hit.facility_id,
                    year_month=year_month,
                    age_class=age_class,
                    applicants=applicants,
                    capacity=capacity,
                    snapshot_date=snapshot_date,
                    source_pdf_url=source_pdf_url,
                    fetched_at=fetched_at,
                )
            )
    return records


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _find_facility_name_column(headers: list[str]) -> int | None:
    for idx, header in enumerate(headers):
        if header.strip() in _FACILITY_NAME_CANDIDATES:
            return idx
    return None


def _index_vacancy_columns(headers: list[str]) -> dict[int, int]:
    """空き状況 PDF: `{age_class: col_idx}`。"""
    result: dict[int, int] = {}
    for idx, header in enumerate(headers):
        match = _VACANCY_COLUMN_RE.match(header.strip())
        if match is None:
            continue
        age = int(match.group("age"))
        result[age] = idx
    return result


def _index_application_columns(headers: list[str]) -> dict[int, dict[str, int]]:
    """申込状況 PDF: `{age_class: {"定員": idx, "申込": idx}}`。"""
    result: dict[int, dict[str, int]] = {}
    for idx, header in enumerate(headers):
        match = _APPLICATION_COLUMN_RE.search(header.strip())
        if match is None:
            continue
        age = int(match.group("age"))
        kind = match.group("kind")
        result.setdefault(age, {})[kind] = idx
    return result


def _read_non_negative_int(row: list[str], col_idx: int | None) -> int | None:
    """セルを非負整数に変換。空白 / `-` / 負数 / 不正フォーマットは None。"""
    if col_idx is None or col_idx >= len(row):
        return None
    cell = row[col_idx].strip()
    if not cell or cell in ("-", "−", "ー"):
        return None
    try:
        value = int(cell.replace(",", ""))
    except ValueError:
        return None
    if value < 0:
        return None
    return value


__all__ = ["parse_application_table", "parse_vacancy_table"]
