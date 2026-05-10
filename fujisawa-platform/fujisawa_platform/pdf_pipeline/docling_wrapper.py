"""Docling wrapper。

Docling は重い ML ライブラリ (PDF の section / table を構造化する) で、
本基盤では optional dep `[pdf]` extra として扱う。consumer (保活 / info-bot)
の ETL Job (proposal 0003 §4.5.4) でのみ利用する想定。

実装方針:
- import は lazy (関数呼出時のみ)
- 戻り値は本基盤独自の `PdfChunk` (Docling の型に直接依存しない)
- 本基盤 Phase 2 では「最小機能」として extract_chunks のみ提供
- 表抽出 / 階層構造の保持は Phase 4 (ETL) で必要に応じて拡張
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DoclingNotInstalledError(ImportError):
    """Docling が optional dep として未インストール。"""


class PdfChunk(BaseModel):
    """Docling 抽出結果の 1 chunk。"""

    model_config = ConfigDict(frozen=True)

    chunk_index: int
    text: str
    page_number: int | None = None


def extract_chunks(pdf_bytes: bytes) -> list[PdfChunk]:
    """PDF bytes を Docling で章別 chunk に構造化する。

    Args:
        pdf_bytes: PDF ファイルの bytes。

    Returns:
        chunk のリスト (出現順、`chunk_index` 0 開始)。

    Raises:
        DoclingNotInstalledError: optional dep `[pdf]` extra が未インストール。
            `uv sync --extra pdf` で導入可能。
    """
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as err:
        raise DoclingNotInstalledError(
            "extract_chunks requires the `docling` package. "
            "Install with: `uv sync --extra pdf`"
        ) from err

    # Docling は file path を要求するため一時ファイル経由
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)

    try:
        converter = DocumentConverter()
        result = converter.convert(tmp_path)
        # Docling document → markdown chunks
        markdown = result.document.export_to_markdown()
        # シンプル分割: 章見出し (## 以上) で split
        # 高度な分割は Phase 4 で改善
        chunks: list[PdfChunk] = []
        current_text: list[str] = []
        chunk_idx = 0
        for line in markdown.splitlines():
            if line.startswith("## ") and current_text:
                chunks.append(
                    PdfChunk(
                        chunk_index=chunk_idx,
                        text="\n".join(current_text).strip(),
                    )
                )
                chunk_idx += 1
                current_text = [line]
            else:
                current_text.append(line)
        if current_text:
            chunks.append(
                PdfChunk(
                    chunk_index=chunk_idx,
                    text="\n".join(current_text).strip(),
                )
            )
        return chunks
    finally:
        tmp_path.unlink(missing_ok=True)
