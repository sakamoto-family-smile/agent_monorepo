"""freshness helper のテスト。"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from fujisawa_platform.models import FreshnessMetadata
from fujisawa_platform.pdf_pipeline.freshness import (
    build_freshness,
    parse_pdf_date_from_filename,
)


class TestBuildFreshness:
    def test_minimum_fields(self) -> None:
        meta = build_freshness(
            source_url="https://www.city.fujisawa.kanagawa.jp/",
        )
        assert isinstance(meta, FreshnessMetadata)
        # as_of は now (UTC) で自動設定される
        delta = (datetime.now(UTC) - meta.as_of).total_seconds()
        assert 0 <= delta < 5

    def test_full_fields(self) -> None:
        fixed_now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        meta = build_freshness(
            source_url="https://www.city.fujisawa.kanagawa.jp/hoiku/.../nyushojokyo.html",
            source_pdf_url="https://www.city.fujisawa.kanagawa.jp/documents/9848/20260115092454.pdf",
            snapshot_date=date(2026, 1, 20),
            etl_job_id="vacancy_etl-20260122-0300",
            schema_version="v1.2",
            as_of=fixed_now,
        )
        assert meta.as_of == fixed_now
        assert meta.snapshot_date == date(2026, 1, 20)
        assert meta.etl_job_id == "vacancy_etl-20260122-0300"
        assert meta.schema_version == "v1.2"


class TestParsePdfDateFromFilename:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            # 藤沢市の典型的な PDF ファイル名パターン (調査 §A2 で確認済)
            ("akizyoukyou20240401-1a.pdf", date(2024, 4, 1)),
            ("mousikomizyoukyou20240401-1.pdf", date(2024, 4, 1)),
            ("20260115092454.pdf", date(2026, 1, 15)),
            # 1 桁日付 (令和 5 年に確認された不規則パターン): 信頼性低のため None
            ("akizyoukyou2023041e.pdf", None),
            # 年なし
            ("r8_navi0129.pdf", None),
            ("foo.pdf", None),
        ],
    )
    def test_extracts_date(self, filename: str, expected: date | None) -> None:
        result = parse_pdf_date_from_filename(filename)
        assert result == expected

    def test_handles_full_url(self) -> None:
        """URL 末尾のファイル名から抽出する。"""
        url = "https://www.city.fujisawa.kanagawa.jp/documents/16736/akizyoukyou20240401-1a.pdf"
        assert parse_pdf_date_from_filename(url) == date(2024, 4, 1)
