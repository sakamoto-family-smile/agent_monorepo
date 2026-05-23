"""edinet-client `_xbrl_parser` のテスト (proposal 0006 Phase 2a)。

Arelle の実 model を mock し、 抽出ロジック単体を検証する。 実 zip 解析は
Arelle 依存・大きな fixture が必要なので、 本ファイルでは行わない (Phase 2b
で stock-analysis-agent 側 integration test で網羅)。
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO

import pytest

from edinet_client import XbrlFinancials, XbrlSegment
from edinet_client._xbrl_parser import (
    _extract_financials,
    _extract_segment_name,
    _filter_consolidated,
    _find_main_xbrl_file,
    _has_non_consolidated_dimension,
    _has_segment_dimension,
    _index_facts_by_concept_localname,
    _infer_period,
    _parse_numeric_value,
    _pick_first_value,
    parse_xbrl_zip,
)

# ──────────────────────────────────────────────────────────────────────
# Arelle ModelXbrl の最小 mock (fact / concept / context / dimension)
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _FakeQName:
    localName: str
    namespaceURI: str = "http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp/2024-11-01/jpcrp_cor"

    def __str__(self) -> str:
        return self.localName

    def __hash__(self) -> int:
        return hash((self.namespaceURI, self.localName))


@dataclass
class _FakeConcept:
    qname: _FakeQName


@dataclass
class _FakeDimValue:
    memberQname: _FakeQName | None


@dataclass
class _FakeContext:
    qnameDims: dict[_FakeQName, _FakeDimValue] = field(default_factory=dict)
    endDatetime: datetime | None = None
    instantDatetime: datetime | None = None


@dataclass
class _FakeFact:
    concept: _FakeConcept
    value: object
    context: _FakeContext | None = None
    xValue: object | None = None


@dataclass
class _FakeModelXbrl:
    facts: list[_FakeFact]


def _make_fact(
    concept_localname: str,
    value: object,
    *,
    end: date | None = None,
    dimensions: dict[str, str] | None = None,
) -> _FakeFact:
    qname = _FakeQName(localName=concept_localname)
    concept = _FakeConcept(qname=qname)
    ctx = _FakeContext()
    if end is not None:
        ctx.endDatetime = datetime.combine(end, datetime.min.time())
    if dimensions:
        ctx.qnameDims = {
            _FakeQName(localName=axis): _FakeDimValue(memberQname=_FakeQName(localName=member))
            for axis, member in dimensions.items()
        }
    return _FakeFact(concept=concept, value=value, context=ctx, xValue=value)


# ──────────────────────────────────────────────────────────────────────
# unit: index / filter / pick helpers
# ──────────────────────────────────────────────────────────────────────


class TestIndexFactsByConcept:
    def test_groups_facts_by_localname(self):
        model = _FakeModelXbrl(
            facts=[
                _make_fact("NetSales", 1000),
                _make_fact("NetSales", 2000),
                _make_fact("OperatingIncome", 300),
            ]
        )
        index = _index_facts_by_concept_localname(model)
        assert set(index.keys()) == {"NetSales", "OperatingIncome"}
        assert len(index["NetSales"]) == 2
        assert len(index["OperatingIncome"]) == 1


class TestConsolidatedFilter:
    def test_removes_non_consolidated_dim(self):
        c_fact = _make_fact("NetSales", 1000)  # consolidated
        s_fact = _make_fact(
            "NetSales",
            500,
            dimensions={"ConsolidatedOrNonConsolidatedAxis": "NonConsolidatedMember"},
        )
        out = _filter_consolidated({"NetSales": [c_fact, s_fact]})
        assert len(out["NetSales"]) == 1
        assert out["NetSales"][0].value == 1000

    def test_keeps_other_dimensions(self):
        f = _make_fact("NetSales", 9999, dimensions={"SegmentAxis": "SegAMember"})
        out = _filter_consolidated({"NetSales": [f]})
        assert out["NetSales"][0].value == 9999

    def test_has_non_consolidated_dimension_helper(self):
        f1 = _make_fact("X", 1, dimensions={"Axis": "NonConsolidatedMember"})
        f2 = _make_fact("X", 2, dimensions={"Axis": "AnyOtherMember"})
        assert _has_non_consolidated_dimension(f1) is True
        assert _has_non_consolidated_dimension(f2) is False


class TestHasSegmentDimension:
    def test_segment_axis_detected(self):
        f = _make_fact("X", 1, dimensions={"ReportableSegmentsAxis": "SegAMember"})
        assert _has_segment_dimension(f) is True

    def test_business_segments_axis_detected(self):
        f = _make_fact("X", 1, dimensions={"BusinessSegmentsAxis": "SegAMember"})
        assert _has_segment_dimension(f) is True

    def test_unrelated_axis_not_detected(self):
        f = _make_fact("X", 1, dimensions={"ConsolidatedOrNonConsolidatedAxis": "X"})
        assert _has_segment_dimension(f) is False


class TestPickFirstValue:
    def test_prefers_first_candidate(self):
        idx = {
            "NetSales": [_make_fact("NetSales", 1000, end=date(2024, 3, 31))],
            "Revenue": [_make_fact("Revenue", 9999, end=date(2024, 3, 31))],
        }
        v, hit = _pick_first_value(
            idx, ("NetSales", "Revenue"), prefer_period_end=date(2024, 3, 31)
        )
        assert v == 1000.0
        assert hit == "NetSales"

    def test_falls_back_to_next_candidate(self):
        idx = {"Revenue": [_make_fact("Revenue", 9999, end=date(2024, 3, 31))]}
        v, hit = _pick_first_value(
            idx, ("NetSales", "Revenue"), prefer_period_end=date(2024, 3, 31)
        )
        assert v == 9999.0
        assert hit == "Revenue"

    def test_returns_none_when_no_candidates(self):
        v, hit = _pick_first_value({}, ("NetSales",), prefer_period_end=None)
        assert v is None
        assert hit is None

    def test_skips_segment_facts(self):
        idx = {
            "NetSales": [
                _make_fact(
                    "NetSales",
                    100,
                    end=date(2024, 3, 31),
                    dimensions={"ReportableSegmentsAxis": "SegAMember"},
                ),
                _make_fact("NetSales", 1000, end=date(2024, 3, 31)),  # full company
            ]
        }
        v, _ = _pick_first_value(idx, ("NetSales",), prefer_period_end=date(2024, 3, 31))
        assert v == 1000.0


class TestParseNumericValue:
    def test_int_value(self):
        assert _parse_numeric_value(_FakeFact(_FakeConcept(_FakeQName("X")), 1234)) == 1234.0

    def test_string_value(self):
        assert _parse_numeric_value(_FakeFact(_FakeConcept(_FakeQName("X")), "5000")) == 5000.0

    def test_none_value(self):
        assert _parse_numeric_value(_FakeFact(_FakeConcept(_FakeQName("X")), None)) is None

    def test_invalid_value(self):
        assert _parse_numeric_value(_FakeFact(_FakeConcept(_FakeQName("X")), "abc")) is None


class TestInferPeriod:
    def test_annual_with_fiscal_year_end(self):
        facts = {
            "CurrentFiscalYearEndDateDEI": [_make_fact("CurrentFiscalYearEndDateDEI", "2024-03-31")],
            "DocumentTypeDEI": [_make_fact("DocumentTypeDEI", "jpcrp030000-asr-001")],
        }
        info = _infer_period(facts)
        assert info["period_end"] == date(2024, 3, 31)
        assert info["period_type"] == "annual"
        assert info["is_consolidated"] is True

    def test_quarterly_doc_type(self):
        facts = {
            "DocumentTypeDEI": [_make_fact("DocumentTypeDEI", "jpcrp040300-q1r-001")],
        }
        info = _infer_period(facts)
        assert info["period_type"] == "quarterly"

    def test_non_consolidated_company(self):
        facts = {
            "WhetherConsolidatedFinancialStatementsArePreparedDEI": [
                _make_fact("WhetherConsolidatedFinancialStatementsArePreparedDEI", "false"),
            ],
        }
        info = _infer_period(facts)
        assert info["is_consolidated"] is False


class TestExtractSegmentName:
    def test_strips_member_suffix(self):
        f = _make_fact(
            "NetSales", 100, dimensions={"ReportableSegmentsAxis": "ElectronicsMember"}
        )
        assert _extract_segment_name(f) == "Electronics"

    def test_ignores_eliminations(self):
        f = _make_fact(
            "NetSales",
            100,
            dimensions={"ReportableSegmentsAxis": "EliminationsOrAdjustmentsMember"},
        )
        assert _extract_segment_name(f) is None

    def test_returns_none_if_no_segment_axis(self):
        f = _make_fact("NetSales", 100, dimensions={"OtherAxis": "AMember"})
        assert _extract_segment_name(f) is None


# ──────────────────────────────────────────────────────────────────────
# integration: _extract_financials の end-to-end (mock model)
# ──────────────────────────────────────────────────────────────────────


class TestExtractFinancialsEndToEnd:
    """`_extract_financials(model)` で Tier 1+2 が一通り取れる確認。"""

    def _build_model(self):
        period_end = date(2024, 3, 31)
        return _FakeModelXbrl(
            facts=[
                # DEI (期メタデータ)
                _make_fact("CurrentFiscalYearEndDateDEI", "2024-03-31"),
                _make_fact("DocumentTypeDEI", "jpcrp030000-asr-001"),
                # Tier 1 P/L
                _make_fact("NetSales", 1_000_000_000, end=period_end),
                _make_fact("OperatingIncome", 100_000_000, end=period_end),
                _make_fact("OrdinaryIncome", 110_000_000, end=period_end),
                _make_fact("ProfitLossAttributableToOwnersOfParent", 70_000_000, end=period_end),
                # Tier 1 BS
                _make_fact("Assets", 5_000_000_000, end=period_end),
                _make_fact("NetAssets", 2_000_000_000, end=period_end),
                # Tier 2 セグメント
                _make_fact(
                    "NetSalesOfReportableSegments",
                    600_000_000,
                    end=period_end,
                    dimensions={"ReportableSegmentsAxis": "ElectronicsMember"},
                ),
                _make_fact(
                    "OperatingIncomeLossOfReportableSegments",
                    60_000_000,
                    end=period_end,
                    dimensions={"ReportableSegmentsAxis": "ElectronicsMember"},
                ),
                _make_fact(
                    "NetSalesOfReportableSegments",
                    400_000_000,
                    end=period_end,
                    dimensions={"ReportableSegmentsAxis": "SoftwareMember"},
                ),
                _make_fact(
                    "OperatingIncomeLossOfReportableSegments",
                    40_000_000,
                    end=period_end,
                    dimensions={"ReportableSegmentsAxis": "SoftwareMember"},
                ),
                # 単体決算値 (除外されるべき)
                _make_fact(
                    "NetSales",
                    900_000_000,
                    end=period_end,
                    dimensions={"ConsolidatedOrNonConsolidatedAxis": "NonConsolidatedMember"},
                ),
            ]
        )

    def test_tier1_extraction(self):
        result = _extract_financials(self._build_model())
        assert result.fiscal_year_end == date(2024, 3, 31)
        assert result.period_type == "annual"
        assert result.is_consolidated is True
        assert result.net_sales == 1_000_000_000
        assert result.operating_profit == 100_000_000
        assert result.ordinary_profit == 110_000_000
        assert result.net_profit == 70_000_000
        assert result.total_assets == 5_000_000_000
        assert result.net_assets == 2_000_000_000
        assert result.has_tier1_data is True

    def test_tier2_segments(self):
        result = _extract_financials(self._build_model())
        assert len(result.segments) == 2
        seg_map = {s.segment_name: s for s in result.segments}
        assert seg_map["Electronics"].net_sales == 600_000_000
        assert seg_map["Electronics"].operating_profit == 60_000_000
        assert seg_map["Software"].net_sales == 400_000_000
        assert seg_map["Software"].operating_profit == 40_000_000

    def test_consolidated_value_chosen_over_single(self):
        """NonConsolidatedMember 付きの fact は無視される (連結優先)。"""
        result = _extract_financials(self._build_model())
        assert result.net_sales == 1_000_000_000  # 連結値、 単体の 9 億ではない

    def test_concept_hits_recorded(self):
        result = _extract_financials(self._build_model())
        assert result.raw_concept_hits["net_sales"] == "NetSales"
        assert result.raw_concept_hits["total_assets"] == "Assets"


class TestExtractFinancialsEmpty:
    def test_empty_model_returns_empty_result(self):
        result = _extract_financials(_FakeModelXbrl(facts=[]))
        assert result.has_tier1_data is False
        assert result.segments == ()

    def test_fallback_to_secondary_concept(self):
        period_end = date(2024, 3, 31)
        model = _FakeModelXbrl(
            facts=[
                _make_fact("CurrentFiscalYearEndDateDEI", "2024-03-31"),
                # IFRS 採用企業: NetSales がなく Revenue のみ
                _make_fact("Revenue", 8_000_000_000, end=period_end),
            ]
        )
        result = _extract_financials(model)
        assert result.net_sales == 8_000_000_000
        assert result.raw_concept_hits["net_sales"] == "Revenue"


# ──────────────────────────────────────────────────────────────────────
# unit: zip 入出力 (Arelle 実呼び出しはしない)
# ──────────────────────────────────────────────────────────────────────


class TestFindMainXbrlFile:
    def test_finds_publicdoc_xbrl(self, tmp_path):
        publicdoc = tmp_path / "XBRL" / "PublicDoc"
        publicdoc.mkdir(parents=True)
        target = publicdoc / "jpcrp030000-asr-001.xbrl"
        target.write_text("dummy")
        assert _find_main_xbrl_file(tmp_path) == target

    def test_falls_back_to_rglob(self, tmp_path):
        other = tmp_path / "somewhere" / "x.xbrl"
        other.parent.mkdir(parents=True)
        other.write_text("dummy")
        assert _find_main_xbrl_file(tmp_path) == other

    def test_returns_none_when_absent(self, tmp_path):
        assert _find_main_xbrl_file(tmp_path) is None


class TestParseXbrlZipErrorHandling:
    def test_invalid_zip_returns_empty_result(self):
        result = parse_xbrl_zip(b"not a zip", document_id="bad")
        assert isinstance(result, XbrlFinancials)
        assert result.has_tier1_data is False

    def test_zip_without_xbrl_returns_empty_result(self):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("README.txt", "no xbrl here")
        result = parse_xbrl_zip(buf.getvalue(), document_id="empty")
        assert isinstance(result, XbrlFinancials)
        assert result.has_tier1_data is False


class TestPublicAPI:
    def test_xbrl_financials_is_frozen(self):
        f = XbrlFinancials(net_sales=100.0)
        with pytest.raises(Exception):  # pydantic v2 raises ValidationError
            f.net_sales = 200.0  # type: ignore[misc]

    def test_xbrl_segment_is_frozen(self):
        s = XbrlSegment(segment_name="A", net_sales=10.0)
        with pytest.raises(Exception):
            s.net_sales = 20.0  # type: ignore[misc]
