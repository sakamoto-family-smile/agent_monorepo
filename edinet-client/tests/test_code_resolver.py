"""EdinetCodeResolver のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from edinet_client import EdinetCodeRecord, EdinetCodeResolver

_FIXTURES = Path(__file__).parent / "fixtures"
_SAMPLE_CSV = _FIXTURES / "Edinetcode_sample.csv"


@pytest.fixture
def resolver() -> EdinetCodeResolver:
    return EdinetCodeResolver.from_csv_path(_SAMPLE_CSV)


class TestCsvLoading:
    def test_loads_all_records(self, resolver: EdinetCodeResolver) -> None:
        # fixture には 5 件
        assert len(resolver) == 5

    def test_from_csv_bytes(self) -> None:
        payload = _SAMPLE_CSV.read_bytes()
        resolver = EdinetCodeResolver.from_csv_bytes(payload)
        assert len(resolver) == 5

    def test_decode_utf8_with_bom(self) -> None:
        text = _SAMPLE_CSV.read_text(encoding="utf-8")
        payload = b"\xef\xbb\xbf" + text.encode("utf-8")  # BOM 付加
        resolver = EdinetCodeResolver.from_csv_bytes(payload)
        assert len(resolver) == 5

    def test_decode_shift_jis(self) -> None:
        text = _SAMPLE_CSV.read_text(encoding="utf-8")
        payload = text.encode("cp932", errors="replace")
        resolver = EdinetCodeResolver.from_csv_bytes(payload)
        assert len(resolver) == 5


class TestResolveEdinetCode:
    def test_4_digit_ticker_with_T_suffix(self, resolver: EdinetCodeResolver) -> None:
        assert resolver.resolve_edinet_code("7203.T") == "E02144"

    def test_4_digit_ticker_bare(self, resolver: EdinetCodeResolver) -> None:
        assert resolver.resolve_edinet_code("7203") == "E02144"

    def test_5_digit_securities_code(self, resolver: EdinetCodeResolver) -> None:
        assert resolver.resolve_edinet_code("72030") == "E02144"

    def test_jp_suffix(self, resolver: EdinetCodeResolver) -> None:
        assert resolver.resolve_edinet_code("6758.JP") == "E03456"

    def test_kioxia_alphanumeric_ticker(self, resolver: EdinetCodeResolver) -> None:
        """2024 年以降の新表記 (alphanumeric ticker) をサポート。 キオクシアは "285A"。"""
        assert resolver.resolve_edinet_code("285A") == "E12345"
        assert resolver.resolve_edinet_code("285A.T") == "E12345"
        assert resolver.resolve_edinet_code("285A0") == "E12345"
        # 小文字でも OK (内部で大文字化)
        assert resolver.resolve_edinet_code("285a.t") == "E12345"

    def test_unlisted_company_not_found_via_securities(
        self, resolver: EdinetCodeResolver
    ) -> None:
        # E02144X は 非上場で securities_code が空 → 証券コード経由では引けない
        assert resolver.resolve_edinet_code("0000") is None

    def test_unknown_ticker_returns_none(self, resolver: EdinetCodeResolver) -> None:
        assert resolver.resolve_edinet_code("9999.T") is None

    def test_empty_string_returns_none(self, resolver: EdinetCodeResolver) -> None:
        assert resolver.resolve_edinet_code("") is None

    def test_invalid_input_returns_none(self, resolver: EdinetCodeResolver) -> None:
        # 3 文字以下、 6 文字以上、 special char は不正
        assert resolver.resolve_edinet_code("abc") is None
        assert resolver.resolve_edinet_code("12") is None
        assert resolver.resolve_edinet_code("123456") is None
        assert resolver.resolve_edinet_code("72-03") is None


class TestResolveSecuritiesCode:
    def test_reverse_lookup(self, resolver: EdinetCodeResolver) -> None:
        assert resolver.resolve_securities_code("E02144") == "72030"
        assert resolver.resolve_securities_code("E03456") == "67580"

    def test_unlisted_returns_none(self, resolver: EdinetCodeResolver) -> None:
        # E02144X は 非上場で securities_code が空欄
        assert resolver.resolve_securities_code("E02144X") is None

    def test_unknown_edinet_code(self, resolver: EdinetCodeResolver) -> None:
        assert resolver.resolve_securities_code("E99999999") is None


class TestGetRecord:
    def test_full_record_fields(self, resolver: EdinetCodeResolver) -> None:
        rec = resolver.get("7203.T")
        assert isinstance(rec, EdinetCodeRecord)
        assert rec.edinet_code == "E02144"
        assert rec.securities_code == "72030"
        assert rec.submitter_name == "トヨタ自動車株式会社"
        assert rec.submitter_name_en == "Toyota Motor Corporation"
        assert rec.industry == "輸送用機器"
        assert rec.corporate_number == "1180301018771"
        assert rec.is_listed is True

    def test_unlisted_record(self, resolver: EdinetCodeResolver) -> None:
        rec = resolver.get_by_edinet_code("E02144X")
        assert rec is not None
        assert rec.securities_code is None
        assert rec.is_listed is False


class TestClientIntegration:
    """EdinetClient に resolver を DI して resolve_edinet_code() が動くこと。"""

    def test_client_resolve_with_resolver(self, resolver: EdinetCodeResolver) -> None:
        from edinet_client import EdinetClient, InMemoryCache

        client = EdinetClient(
            api_key="test", cache=InMemoryCache(), code_resolver=resolver
        )
        assert client.resolve_edinet_code("7203.T") == "E02144"
        assert client.resolve_edinet_code("9999.T") is None

    def test_client_resolve_without_resolver_raises(self) -> None:
        from edinet_client import EdinetClient, InMemoryCache

        client = EdinetClient(api_key="test", cache=InMemoryCache())
        with pytest.raises(RuntimeError, match="code_resolver"):
            client.resolve_edinet_code("7203.T")
