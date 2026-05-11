"""PDF からの表抽出 helper (Docling lazy import)。

`docling_wrapper.extract_chunks` がテキスト本文を chunk 化するのに対し、
本モジュールは Docling が認識した **表構造** を `PdfTable` に取り出す。

利用先 (Phase 4-2c 以降):
- `biyearly_admission_etl`: 4 月入所結果 PDF (1 次・2 次) の表
- `monthly_vacancy_etl`: 空き状況 / 申込状況 PDF の表 (Phase 4-2d)
- `wayback_backfill`: 令和 4 年最低指数 PDF の表 (Phase 4-2g)

各 ETL はこの helper が返す `PdfTable` を自前の parser で `*Record` に変換する。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DoclingNotInstalledError(ImportError):
    """Docling が optional dep として未インストール。"""


class PdfTable(BaseModel):
    """Docling が抽出した 1 つの表を表すモデル (`_html_table.HtmlTable` と同形)。"""

    model_config = ConfigDict(frozen=True)

    headers: list[str]
    rows: list[list[str]]
    page_number: int | None = None


def extract_tables(pdf_bytes: bytes) -> list[PdfTable]:
    """PDF bytes を Docling で解析し、含まれる表を `PdfTable` のリストで返す。

    Args:
        pdf_bytes: PDF ファイルの bytes。

    Returns:
        ページ順に並んだ `PdfTable` のリスト。表が無い PDF は空 list。

    Raises:
        DoclingNotInstalledError: optional dep `[pdf]` extra が未インストール。
            `uv sync --extra pdf` で導入可能。
    """
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as err:
        raise DoclingNotInstalledError(
            "extract_tables requires the `docling` package. Install with: `uv sync --extra pdf`"
        ) from err

    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)

    try:
        converter = DocumentConverter()
        result = converter.convert(tmp_path)
        return _docling_tables_to_pdf_tables(result.document)
    finally:
        tmp_path.unlink(missing_ok=True)


def _docling_tables_to_pdf_tables(document: object) -> list[PdfTable]:
    """Docling Document の tables 属性を `PdfTable` に変換。

    Docling のテーブル API はバージョンで微妙に違うが、`tables` 属性に list が
    入っており、各要素は `data.grid` (list[list[cell]]) 相当の構造を持つ。
    """
    tables_attr = getattr(document, "tables", None)
    if not tables_attr:
        return []

    result: list[PdfTable] = []
    for table in tables_attr:
        grid = _extract_grid(table)
        if not grid:
            continue
        headers = grid[0] if grid else []
        rows = grid[1:] if len(grid) > 1 else []
        page_number = _extract_page_number(table)
        result.append(PdfTable(headers=headers, rows=rows, page_number=page_number))
    return result


def _extract_grid(table: object) -> list[list[str]]:
    """Docling のテーブル 1 つ分から 2D string grid を抽出 (best-effort)。"""
    data = getattr(table, "data", None)
    grid = getattr(data, "grid", None) if data is not None else None
    if not grid:
        return []
    result: list[list[str]] = []
    for row in grid:
        result.append([_cell_text(cell) for cell in row])
    return result


def _cell_text(cell: object) -> str:
    text = getattr(cell, "text", None)
    if text is None:
        return str(cell)
    return str(text).strip()


def _extract_page_number(table: object) -> int | None:
    prov = getattr(table, "prov", None)
    if not prov:
        return None
    first = prov[0] if prov else None
    if first is None:
        return None
    page_no = getattr(first, "page_no", None)
    if page_no is None:
        return None
    try:
        return int(page_no)
    except (TypeError, ValueError):
        return None


__all__ = ["DoclingNotInstalledError", "PdfTable", "extract_tables"]
