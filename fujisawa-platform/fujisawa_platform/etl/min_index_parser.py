r"""令和 4 年最低指数 PDF (`r4-4nyuusyonaiteisisuu.pdf`) parser。

調査ノート §A2-2 で確認した PDF 構造:
- 3 ページ・220 KB
- 120+ 施設 × age_class 0..5 の表
- 各セルは `<基礎点><優先順位><調整>` 形式 (例: `10F11`) または以下のマーカー:
  - `※`: 同点細目あり (`10F11※`)
  - `△`: 内定者 1 名 (個人情報保護で非公開)
  - `○`: 定員に空きあり
  - `-` / `−`: 空きなし
  - `＼`: クラスなし

実 Docling 出力 (2026-05-14 実 GCP 実行 + ローカル再現で確認) の構造:
- 4 tables (公立 / 認可 / 小規模 / 家庭的保育)
- header は `['公立', '０歳', '１歳', ..., '５歳']` のように **全角数字 + `歳`** で来る
  (旧 parser が想定した `施設名 + 0歳児` 形式と乖離)
- 一部 table は Docling が改ページで header を取りこぼし、データ行を headers に
  入れてしまう (`['にじいろ保育園藤沢', '10F11※', ...]` のように)
- 家庭的保育の `0歳～2歳` のような range header は本 parser では skip
  (data がほぼ `○` マーカーで実質意味が無いため)

このため:
1. age column regex は `^[0-5０-５]\s*歳(児|児クラス|)\s*$` で半角/全角・歳/歳児 両対応
2. facility name column は `施設名 / 保育施設名 / 園名` が無ければ「age col より
   左の col 0」を heuristic で採用
3. 複数 table を context-aware に処理する `parse_min_index_tables` を提供し、
   age column が検出できなかった table では **前 table の column 設計を継承して
   headers をデータ行として再 parse** することで Docling header miss を救済

`parse_min_index_tables` は `MinIndexEntry` のリストを返す。マーカーセル / 不正
フォーマット / resolver で解決できない施設は skip。
最終的に `wayback_backfill` (Phase 4-2g) が `admission_results.min_*` 4 フィールドに
反映する。
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from fujisawa_platform.etl.admission_parser import parse_min_index_notation
from fujisawa_platform.pdf_pipeline import PdfTable
from fujisawa_platform.resolver import FacilityResolver, NoMatchError

_AGE_COLUMN_RE = re.compile(r"^(?P<age>[0-5０-５])\s*歳(児|児クラス)?\s*$")
_FACILITY_NAME_CANDIDATES = ("施設名", "保育施設名", "園名")
_FULLWIDTH_DIGIT_OFFSET = ord("０") - ord("0")


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
    """令和 4 年最低指数 PDF の表 1 つを `MinIndexEntry` のリストに変換 (単体 table 版)。

    `parse_min_index_tables` の単一 table 版互換 API。Docling header miss の救済が
    必要なケースでは `parse_min_index_tables` を使うこと。
    """
    facility_col = _find_facility_name_column(table.headers)
    if facility_col is None:
        return []
    age_columns = _index_age_columns(table.headers)
    if not age_columns:
        return []
    return _parse_rows(
        rows=table.rows,
        facility_col=facility_col,
        age_columns=age_columns,
        source_pdf_url=source_pdf_url,
        resolver=resolver,
    )


def parse_min_index_tables(
    *,
    tables: list[PdfTable],
    source_pdf_url: str,
    resolver: FacilityResolver,
) -> list[MinIndexEntry]:
    """複数 table を context-aware に処理し、Docling header miss にも対応する。

    各 table を逐次走査し、`_index_age_columns` で age 列が検出できれば通常処理。
    検出できなかった (かつ既に正常な table を 1 つ以上処理済の) table は、Docling
    が改ページで header を取りこぼした **継続表** と判断し、前 table の
    `(facility_col, age_columns)` をそのまま流用して headers + rows をまとめて
    データとして再 parse する。
    """
    entries: list[MinIndexEntry] = []
    last_facility_col: int | None = None
    last_age_columns: dict[int, int] | None = None

    for table in tables:
        age_columns = _index_age_columns(table.headers)
        if age_columns:
            facility_col = _resolve_facility_column(table.headers, age_columns)
            last_facility_col = facility_col
            last_age_columns = age_columns
            entries.extend(
                _parse_rows(
                    rows=table.rows,
                    facility_col=facility_col,
                    age_columns=age_columns,
                    source_pdf_url=source_pdf_url,
                    resolver=resolver,
                )
            )
        elif last_age_columns is not None and last_facility_col is not None:
            virtual_rows: list[list[str]] = [list(table.headers), *table.rows]
            entries.extend(
                _parse_rows(
                    rows=virtual_rows,
                    facility_col=last_facility_col,
                    age_columns=last_age_columns,
                    source_pdf_url=source_pdf_url,
                    resolver=resolver,
                )
            )

    return entries


def _find_facility_name_column(headers: list[str]) -> int | None:
    for idx, header in enumerate(headers):
        if header.strip() in _FACILITY_NAME_CANDIDATES:
            return idx
    return None


def _resolve_facility_column(headers: list[str], age_columns: dict[int, int]) -> int:
    """Facility name column を判定。

    1. `_FACILITY_NAME_CANDIDATES` に完全一致する header があればその col
    2. 無ければ age column より左の最も左 col (慣例で col 0)
    """
    explicit = _find_facility_name_column(headers)
    if explicit is not None:
        return explicit
    leftmost_age = min(age_columns.values())
    return 0 if leftmost_age > 0 else 0


def _index_age_columns(headers: list[str]) -> dict[int, int]:
    """`{age_class: col_idx}` の対応。半角 `0歳児` / 全角 `０歳` 等を統一して扱う。"""
    result: dict[int, int] = {}
    for idx, header in enumerate(headers):
        match = _AGE_COLUMN_RE.match(header.strip())
        if match is None:
            continue
        result[_normalize_digit(match.group("age"))] = idx
    return result


def _normalize_digit(ch: str) -> int:
    """半角 `0`..`5` / 全角 `０`..`５` を int 0..5 に揃える。"""
    code = ord(ch)
    if ord("0") <= code <= ord("5"):
        return code - ord("0")
    return code - ord("０")


def _parse_rows(
    *,
    rows: list[list[str]],
    facility_col: int,
    age_columns: dict[int, int],
    source_pdf_url: str,
    resolver: FacilityResolver,
) -> list[MinIndexEntry]:
    entries: list[MinIndexEntry] = []
    for row in rows:
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
                continue
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


__all__ = [
    "MinIndexEntry",
    "parse_min_index_table",
    "parse_min_index_tables",
]
