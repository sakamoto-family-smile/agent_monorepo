"""docling_wrapper のテスト。

Docling 本体は重い ML ライブラリ (optional dep `[pdf]` extra) なので、
ライブラリ未インストール時の挙動 (適切な ImportError) を中心に検証する。

実際の PDF 構造化テストは Phase 2.5 で `@pytest.mark.integration` として追加。
"""

from __future__ import annotations

import pytest

from fujisawa_platform.pdf_pipeline.docling_wrapper import (
    DoclingNotInstalledError,
    PdfChunk,
)


class TestPdfChunk:
    def test_immutable_with_required_fields(self) -> None:
        chunk = PdfChunk(
            chunk_index=0,
            text="第 1 章 はじめに",
            page_number=1,
        )
        assert chunk.chunk_index == 0
        assert chunk.text == "第 1 章 はじめに"
        assert chunk.page_number == 1
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            chunk.text = "modified"  # type: ignore[misc]

    def test_optional_page_number(self) -> None:
        chunk = PdfChunk(chunk_index=0, text="text", page_number=None)
        assert chunk.page_number is None


class TestDoclingLazyImport:
    def test_extract_chunks_raises_when_not_installed(self) -> None:
        """Docling 未インストール時は適切な ImportError 派生例外を上げる。

        本テストは docling が optional dep のため、CI ではインストールされて
        いない前提で動く。インストール済 (実装側で Docling 本体検出) のときは
        skip する。
        """
        try:
            import docling  # noqa: F401
        except ImportError:
            pass
        else:
            pytest.skip("docling is installed; lazy-import test is N/A")

        from fujisawa_platform.pdf_pipeline.docling_wrapper import extract_chunks

        with pytest.raises(DoclingNotInstalledError):
            extract_chunks(b"%PDF-1.4 fake content")
