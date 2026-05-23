"""orchestrator の XBRL → Claude prompt 整形ロジックのテスト (Phase 2b)。

`_format_xbrl_financials_section` / `_fmt_amount` の挙動を検証する。 実際の
Claude SDK 呼び出しはここではしない。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from edinet_client import (
    DocumentBody,
    DocumentMetadata,
    DocumentType,
    XbrlFinancials,
    XbrlSegment,
)

from agents.edinet_collector import EdinetFilingResult
from agents.orchestrator import _fmt_amount, _format_xbrl_financials_section


def _make_filing(
    *,
    doc_id: str,
    doc_type: DocumentType,
    submit_date: date,
    financials: XbrlFinancials | None = None,
) -> EdinetFilingResult:
    meta = DocumentMetadata(
        document_id=doc_id,
        edinet_code="E12345",
        securities_code="285A0",
        submitter_name="キオクシア",
        document_type=doc_type,
        submit_date=submit_date,
        xbrl_flag=financials is not None,
        pdf_flag=True,
    )
    body = DocumentBody(
        document_id=doc_id,
        content_type="pdf",
        bytes_payload=b"fake-pdf",
        fetched_at=datetime.now(UTC),
        from_cache=False,
    )
    return EdinetFilingResult(metadata=meta, body=body, financials=financials)


class TestFmtAmount:
    def test_none(self):
        assert _fmt_amount(None) == "—"

    def test_trillions(self):
        assert _fmt_amount(1.5e12) == "1.50 兆円"

    def test_billions(self):
        assert _fmt_amount(8_000_000_000.0) == "80 億円"

    def test_hundred_millions_threshold(self):
        # 1.5 億 → 「2 億円」 (rounded)
        assert _fmt_amount(150_000_000.0) == "2 億円"

    def test_millions(self):
        assert _fmt_amount(50_000_000.0) == "50 百万円"

    def test_small_amount(self):
        assert _fmt_amount(500_000.0) == "500,000 円"

    def test_negative(self):
        assert _fmt_amount(-200_000_000_000.0) == "-2,000 億円"


class TestFormatXbrlSection:
    def test_returns_empty_when_no_financials(self):
        filings = [_make_filing(
            doc_id="A1",
            doc_type=DocumentType.ANNUAL_REPORT,
            submit_date=date(2026, 5, 10),
            financials=None,
        )]
        assert _format_xbrl_financials_section(filings) == ""

    def test_tier1_table_rendered(self):
        fin = XbrlFinancials(
            fiscal_year_end=date(2026, 3, 31),
            period_type="annual",
            net_sales=1_500_000_000_000.0,
            operating_profit=200_000_000_000.0,
            ordinary_profit=210_000_000_000.0,
            net_profit=150_000_000_000.0,
            total_assets=3_000_000_000_000.0,
            net_assets=1_000_000_000_000.0,
        )
        section = _format_xbrl_financials_section(
            [_make_filing(
                doc_id="A1",
                doc_type=DocumentType.ANNUAL_REPORT,
                submit_date=date(2026, 5, 10),
                financials=fin,
            )]
        )
        assert "Tier 1" in section
        assert "1.50 兆円" in section
        assert "有価証券報告書" in section
        assert "2026-03-31" in section

    def test_tier2_segments_rendered_for_annual(self):
        fin = XbrlFinancials(
            fiscal_year_end=date(2026, 3, 31),
            net_sales=1_000_000_000_000.0,
            segments=(
                XbrlSegment(
                    segment_name="Memory",
                    net_sales=800_000_000_000.0,
                    operating_profit=80_000_000_000.0,
                ),
                XbrlSegment(
                    segment_name="Storage",
                    net_sales=200_000_000_000.0,
                    operating_profit=20_000_000_000.0,
                ),
            ),
        )
        section = _format_xbrl_financials_section(
            [_make_filing(
                doc_id="A1",
                doc_type=DocumentType.ANNUAL_REPORT,
                submit_date=date(2026, 5, 10),
                financials=fin,
            )]
        )
        assert "Tier 2" in section
        assert "Memory" in section
        assert "Storage" in section
        assert "8,000 億円" in section

    def test_multiple_periods_in_tier1(self):
        annual_fin = XbrlFinancials(
            fiscal_year_end=date(2026, 3, 31),
            net_sales=1_000_000_000_000.0,
        )
        q_fin = XbrlFinancials(
            fiscal_year_end=date(2025, 12, 31),
            net_sales=250_000_000_000.0,
        )
        section = _format_xbrl_financials_section([
            _make_filing(
                doc_id="A1",
                doc_type=DocumentType.ANNUAL_REPORT,
                submit_date=date(2026, 5, 10),
                financials=annual_fin,
            ),
            _make_filing(
                doc_id="Q3",
                doc_type=DocumentType.QUARTERLY_REPORT,
                submit_date=date(2026, 2, 14),
                financials=q_fin,
            ),
        ])
        # 両期分が表に出る
        assert "2026-03-31" in section
        assert "2025-12-31" in section
        assert "1.00 兆円" in section
        assert "2,500 億円" in section
        # 四半期にはセグメント情報を出さない (Tier 2 は有報優先)
        assert "Tier 2" not in section
