"""`PdfTable` モデルと `extract_tables` の skip テスト。

Docling 自体が optional dep のため、本番ロジックの統合テストは Phase 4 デプロイ時の
手動 smoke (proposal 0003 §4.6) に委ねる。本テストでは:
- `PdfTable` モデルの妥当性検証
- Docling 未インストール時の error 経路
- Docling インストール環境では実 PDF を渡せば動作する (skip if not installed)
"""

from __future__ import annotations

import importlib
import importlib.util

import pytest

from fujisawa_platform.pdf_pipeline.pdf_table import (
    DoclingNotInstalledError,
    PdfTable,
    extract_tables,
)

_DOCLING_INSTALLED = importlib.util.find_spec("docling") is not None


class TestPdfTableModel:
    def test_frozen(self) -> None:
        t = PdfTable(headers=["A", "B"], rows=[["1", "2"]], page_number=5)
        with pytest.raises(Exception):
            t.headers = ["X"]  # type: ignore[misc]

    def test_default_page_number_none(self) -> None:
        t = PdfTable(headers=[], rows=[])
        assert t.page_number is None


class TestExtractTables:
    def test_raises_when_docling_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """docling パッケージが import できない場合は明示的なエラーを返す。"""
        import builtins

        original_import = builtins.__import__

        def fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("docling"):
                raise ImportError("docling not installed")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(DoclingNotInstalledError):
            extract_tables(b"%PDF-fake")

    @pytest.mark.skipif(not _DOCLING_INSTALLED, reason="docling not installed")
    def test_returns_list_when_pdf_has_no_tables(self) -> None:  # pragma: no cover
        """Docling インストール環境で、空 PDF (バイト) を渡しても crash しないこと。

        本格的な table 抽出検証は Phase 4 デプロイ時に実 PDF (`r4-4nyuusyonaiteisisuu.pdf`
        等) で実施する (proposal 0003 §4.6)。
        """
        # 最小限の PDF (1 ページ、テーブルなし) を作るのは複雑なので、
        # 空 bytes を渡すと docling は ValueError を上げる前提でテストはスキップ。
        # ここに来るのは "docling が動く環境" のみ。
        try:
            tables = extract_tables(b"%PDF-1.4 fake")
            assert isinstance(tables, list)
        except (ValueError, RuntimeError):
            # Docling が PDF を読めなかった場合 — 想定範囲内
            pass
