"""edinet_collector のテスト (実 EDINET API は叩かない)。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from edinet_client import (
    DocumentBody,
    DocumentMetadata,
    DocumentType,
    EdinetCodeResolver,
)


_SAMPLE_CSV = Path(__file__).parent / ".." / "tests_fixtures_edinet.csv"


@pytest.fixture(autouse=True)
def _set_csv_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """テスト用に Edinetcode.csv 相当を tmp に書き、 settings.edinet_code_csv_path に直接 set。

    `Settings` クラスは class 属性レベルで env を評価するため、 monkeypatch.setenv では
    既に設定済の値を上書きできない。 settings インスタンスを直接書き換える。
    """
    csv_text = (
        "ダウンロード日時：2026-05-23,,,,,,,,,,,,\n"
        "ＥＤＩＮＥＴコード,提出者種別,上場区分,連結の有無,資本金,決算日,"
        "提出者名,提出者名（英字）,提出者名（ヨミ）,所在地,提出者業種,証券コード,提出者法人番号\n"
        "E12345,内国法人・株式会社,上場,有,1000000000,3月31日,"
        "キオクシアホールディングス,Kioxia,キオクシア,東京都港区,電気機器,285A0,1234567890123\n"
        "E02144,内国法人・株式会社,上場,有,635401000000,3月31日,"
        "トヨタ自動車,Toyota,トヨタ,愛知県豊田市,輸送用機器,72030,1180301018771\n"
    )
    csv_path = tmp_path / "Edinetcode.csv"
    csv_path.write_text(csv_text, encoding="utf-8")
    from config import settings

    monkeypatch.setattr(settings, "edinet_code_csv_path", str(csv_path), raising=False)
    return csv_path


def _stub_settings(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    """`config.settings` の属性を直接書き換える (env 経由より素早い)。"""
    from config import settings

    defaults = {
        "edinet_enabled": True,
        "edinet_api_key": "test-key",
        "edinet_cache_backend": "local",
        "edinet_cache_root": "./_test_edinet_cache",
        "edinet_search_window_days": 5,
        "edinet_quarterly_lookback": 2,
        "edinet_min_interval_sec": 0.001,
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        monkeypatch.setattr(settings, k, v, raising=False)


def _make_metadata(
    *,
    doc_id: str,
    edinet_code: str,
    doc_type: DocumentType,
    submit_date: date,
) -> DocumentMetadata:
    return DocumentMetadata(
        document_id=doc_id,
        edinet_code=edinet_code,
        securities_code="285A0",
        submitter_name="キオクシア",
        document_type=doc_type,
        submit_date=submit_date,
        description=f"{doc_type.name} ({submit_date})",
    )


def _make_body(doc_id: str) -> DocumentBody:
    return DocumentBody(
        document_id=doc_id,
        content_type="pdf",
        bytes_payload=b"%PDF-1.4 fake content for " + doc_id.encode(),
        fetched_at=datetime.now(UTC),
        from_cache=False,
    )


# ─────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────


class TestFeatureFlag:
    @pytest.mark.asyncio
    async def test_returns_empty_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_settings(monkeypatch, edinet_enabled=False)
        from agents.edinet_collector import collect_filings

        result = await collect_filings("285A.T")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_api_key_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_settings(monkeypatch, edinet_api_key="")
        from agents.edinet_collector import collect_filings

        result = await collect_filings("285A.T")
        assert result == []


class TestTickerResolution:
    @pytest.mark.asyncio
    async def test_returns_empty_when_csv_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _stub_settings(monkeypatch)
        from config import settings as _s

        monkeypatch.setattr(_s, "edinet_code_csv_path", str(tmp_path / "missing.csv"))
        from agents.edinet_collector import collect_filings

        assert await collect_filings("285A.T") == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_ticker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_settings(monkeypatch)
        # client を呼ぶ前に code resolver で None になるので、 stub 不要
        from agents.edinet_collector import collect_filings

        assert await collect_filings("9999.T") == []


class TestCollectionFlow:
    @pytest.mark.asyncio
    async def test_collects_annual_and_quarterlies_for_kioxia(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """キオクシア (285A.T) の有報 1 + 四半期 2 を取得して downloads される。"""
        _stub_settings(monkeypatch, edinet_quarterly_lookback=2, edinet_search_window_days=10)

        # 模擬: EdinetClient を fake に置換
        from agents import edinet_collector

        annual = _make_metadata(
            doc_id="ANNUAL1",
            edinet_code="E12345",
            doc_type=DocumentType.ANNUAL_REPORT,
            submit_date=date(2026, 5, 10),
        )
        q3 = _make_metadata(
            doc_id="Q3",
            edinet_code="E12345",
            doc_type=DocumentType.QUARTERLY_REPORT,
            submit_date=date(2026, 2, 14),
        )
        q4 = _make_metadata(
            doc_id="Q4",
            edinet_code="E12345",
            doc_type=DocumentType.QUARTERLY_REPORT,
            submit_date=date(2025, 11, 14),
        )
        unrelated = _make_metadata(
            doc_id="OTHER",
            edinet_code="E02144",  # トヨタ
            doc_type=DocumentType.ANNUAL_REPORT,
            submit_date=date(2026, 5, 1),
        )
        all_docs = [annual, q3, q4, unrelated]

        downloaded: list[str] = []

        class _FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "_FakeClient":
                return self

            async def __aexit__(self, *exc: Any) -> None:
                return None

            async def list_documents(self, target_date: date) -> list[DocumentMetadata]:
                # window 内のどこかで 4 件全部返す。 重複 dedup は collector 側に
                # 期待しない (実装上 dedup していない); 検証は target id 集合で
                if target_date == date.today():
                    return all_docs
                return []

            async def download(self, doc_id: str, *, content_type: str = "pdf") -> DocumentBody:
                downloaded.append(doc_id)
                return _make_body(doc_id)

        monkeypatch.setattr(edinet_collector, "EdinetClient", _FakeClient)

        results = await edinet_collector.collect_filings("285A.T")

        # キオクシアの有報 + 四半期 2 件 = 3 件
        assert len(results) == 3
        downloaded_ids = sorted(downloaded)
        # 関係ない E02144 (トヨタ) は含まれない
        assert "OTHER" not in downloaded_ids
        assert sorted([r.metadata.document_id for r in results]) == ["ANNUAL1", "Q3", "Q4"]

        # 提出日 昇順ソートの確認
        dates = [r.metadata.submit_date for r in results]
        assert dates == sorted(dates)

    @pytest.mark.asyncio
    async def test_download_failure_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """1 件の download 失敗で全体を落とさず、 他は採用される。"""
        _stub_settings(monkeypatch, edinet_quarterly_lookback=1, edinet_search_window_days=5)

        from agents import edinet_collector

        annual = _make_metadata(
            doc_id="ANNUAL1",
            edinet_code="E12345",
            doc_type=DocumentType.ANNUAL_REPORT,
            submit_date=date(2026, 5, 10),
        )
        q3 = _make_metadata(
            doc_id="QBAD",
            edinet_code="E12345",
            doc_type=DocumentType.QUARTERLY_REPORT,
            submit_date=date(2026, 2, 14),
        )

        class _FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "_FakeClient":
                return self

            async def __aexit__(self, *exc: Any) -> None:
                return None

            async def list_documents(self, target_date: date) -> list[DocumentMetadata]:
                if target_date == date.today():
                    return [annual, q3]
                return []

            async def download(self, doc_id: str, *, content_type: str = "pdf") -> DocumentBody:
                if doc_id == "QBAD":
                    raise RuntimeError("simulated download failure")
                return _make_body(doc_id)

        monkeypatch.setattr(edinet_collector, "EdinetClient", _FakeClient)

        results = await edinet_collector.collect_filings("285A.T")
        # 失敗 1 件分は除外、 残り 1 件
        assert len(results) == 1
        assert results[0].metadata.document_id == "ANNUAL1"


class TestSemiAnnualSelection:
    """Phase 2c: `_select_target_filings` が半期報告書 (160) も中間期として
    扱う。 2024-04 金商法改正で多くの企業が四半期 (140) を廃止して半期 (160)
    のみ提出するようになったため、 両者を統一的に target とする。
    """

    def test_select_includes_semi_annual_as_interim(self):
        from agents.edinet_collector import _select_target_filings

        annual = _make_metadata(
            doc_id="ANN",
            edinet_code="E12345",
            doc_type=DocumentType.ANNUAL_REPORT,
            submit_date=date(2025, 6, 25),
        )
        semi1 = _make_metadata(
            doc_id="SEMI_1",
            edinet_code="E12345",
            doc_type=DocumentType.SEMI_ANNUAL_REPORT,
            submit_date=date(2025, 11, 14),
        )
        semi0 = _make_metadata(
            doc_id="SEMI_0",
            edinet_code="E12345",
            doc_type=DocumentType.SEMI_ANNUAL_REPORT,
            submit_date=date(2024, 11, 14),
        )
        result = _select_target_filings([annual, semi1, semi0], n_quarters=2)
        ids = sorted(r.document_id for r in result)
        assert ids == ["ANN", "SEMI_0", "SEMI_1"]

    def test_select_mixed_quarterly_and_semi(self):
        """混在 (改正前後で報告形態が変わった企業) でも新しい順に N 件採用。"""
        from agents.edinet_collector import _select_target_filings

        docs = [
            _make_metadata(
                doc_id="ANN",
                edinet_code="E12345",
                doc_type=DocumentType.ANNUAL_REPORT,
                submit_date=date(2025, 6, 25),
            ),
            _make_metadata(
                doc_id="Q_NEW",
                edinet_code="E12345",
                doc_type=DocumentType.QUARTERLY_REPORT,
                submit_date=date(2026, 2, 14),
            ),
            _make_metadata(
                doc_id="SEMI_NEW",
                edinet_code="E12345",
                doc_type=DocumentType.SEMI_ANNUAL_REPORT,
                submit_date=date(2025, 11, 14),
            ),
            _make_metadata(
                doc_id="SEMI_OLD",
                edinet_code="E12345",
                doc_type=DocumentType.SEMI_ANNUAL_REPORT,
                submit_date=date(2024, 11, 14),
            ),
        ]
        result = _select_target_filings(docs, n_quarters=2)
        ids = sorted(r.document_id for r in result)
        # 有報 + 新しい順 2 件
        assert ids == ["ANN", "Q_NEW", "SEMI_NEW"]


class TestXbrlIntegration:
    """Phase 2b: collector が PDF + XBRL を両方取得して financials を埋める。"""

    @pytest.mark.asyncio
    async def test_xbrl_parsed_when_flag_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_settings(
            monkeypatch,
            edinet_quarterly_lookback=0,
            edinet_search_window_days=3,
            edinet_enable_xbrl=True,
        )
        from agents import edinet_collector
        from edinet_client import XbrlFinancials

        annual = DocumentMetadata(
            document_id="ANNUAL_X",
            edinet_code="E12345",
            securities_code="285A0",
            submitter_name="キオクシア",
            document_type=DocumentType.ANNUAL_REPORT,
            submit_date=date(2026, 5, 10),
            xbrl_flag=True,  # XBRL あり
            pdf_flag=True,
        )

        download_calls: list[tuple[str, str]] = []

        class _FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "_FakeClient":
                return self

            async def __aexit__(self, *exc: Any) -> None:
                return None

            async def list_documents(self, target_date: date) -> list[DocumentMetadata]:
                if target_date == date.today():
                    return [annual]
                return []

            async def download(self, doc_id: str, *, content_type: str = "pdf") -> DocumentBody:
                download_calls.append((doc_id, content_type))
                return DocumentBody(
                    document_id=doc_id,
                    content_type=content_type,
                    bytes_payload=b"fake-" + content_type.encode(),
                    fetched_at=datetime.now(UTC),
                    from_cache=False,
                )

        # XBRL parser を stub: 適当な financials を返す
        fake_fin = XbrlFinancials(
            fiscal_year_end=date(2026, 3, 31),
            net_sales=1_000_000_000_000.0,
            operating_profit=100_000_000_000.0,
        )

        def _fake_parse(zip_bytes: bytes, *, document_id: str | None = None):
            return fake_fin

        monkeypatch.setattr(edinet_collector, "EdinetClient", _FakeClient)
        monkeypatch.setattr(edinet_collector, "parse_xbrl_zip", _fake_parse)

        results = await edinet_collector.collect_filings("285A.T")
        assert len(results) == 1
        assert results[0].financials == fake_fin
        # PDF と XBRL の両方が DL されたか
        contents = sorted(ct for _, ct in download_calls)
        assert contents == ["pdf", "xbrl_zip"]

    @pytest.mark.asyncio
    async def test_xbrl_skipped_when_flag_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_settings(
            monkeypatch,
            edinet_quarterly_lookback=0,
            edinet_search_window_days=3,
            edinet_enable_xbrl=True,
        )
        from agents import edinet_collector

        annual = DocumentMetadata(
            document_id="A_NO_XBRL",
            edinet_code="E12345",
            securities_code="285A0",
            submitter_name="キオクシア",
            document_type=DocumentType.ANNUAL_REPORT,
            submit_date=date(2026, 5, 10),
            xbrl_flag=False,
            pdf_flag=True,
        )

        download_calls: list[tuple[str, str]] = []

        class _FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "_FakeClient":
                return self

            async def __aexit__(self, *exc: Any) -> None:
                return None

            async def list_documents(self, target_date: date) -> list[DocumentMetadata]:
                if target_date == date.today():
                    return [annual]
                return []

            async def download(self, doc_id: str, *, content_type: str = "pdf") -> DocumentBody:
                download_calls.append((doc_id, content_type))
                return _make_body(doc_id)

        monkeypatch.setattr(edinet_collector, "EdinetClient", _FakeClient)

        results = await edinet_collector.collect_filings("285A.T")
        assert len(results) == 1
        assert results[0].financials is None
        # xbrl_zip download は呼ばれていない
        assert all(ct == "pdf" for _, ct in download_calls)

    @pytest.mark.asyncio
    async def test_xbrl_skipped_when_feature_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_settings(
            monkeypatch,
            edinet_quarterly_lookback=0,
            edinet_search_window_days=3,
            edinet_enable_xbrl=False,  # ← off
        )
        from agents import edinet_collector

        annual = DocumentMetadata(
            document_id="A_OFF",
            edinet_code="E12345",
            securities_code="285A0",
            submitter_name="キオクシア",
            document_type=DocumentType.ANNUAL_REPORT,
            submit_date=date(2026, 5, 10),
            xbrl_flag=True,  # XBRL あるが feature off
            pdf_flag=True,
        )

        download_calls: list[tuple[str, str]] = []

        class _FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "_FakeClient":
                return self

            async def __aexit__(self, *exc: Any) -> None:
                return None

            async def list_documents(self, target_date: date) -> list[DocumentMetadata]:
                if target_date == date.today():
                    return [annual]
                return []

            async def download(self, doc_id: str, *, content_type: str = "pdf") -> DocumentBody:
                download_calls.append((doc_id, content_type))
                return _make_body(doc_id)

        monkeypatch.setattr(edinet_collector, "EdinetClient", _FakeClient)

        results = await edinet_collector.collect_filings("285A.T")
        assert len(results) == 1
        assert results[0].financials is None
        assert all(ct == "pdf" for _, ct in download_calls)

    @pytest.mark.asyncio
    async def test_xbrl_download_failure_keeps_pdf(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_settings(
            monkeypatch,
            edinet_quarterly_lookback=0,
            edinet_search_window_days=3,
            edinet_enable_xbrl=True,
        )
        from agents import edinet_collector

        annual = DocumentMetadata(
            document_id="A_XFAIL",
            edinet_code="E12345",
            securities_code="285A0",
            submitter_name="キオクシア",
            document_type=DocumentType.ANNUAL_REPORT,
            submit_date=date(2026, 5, 10),
            xbrl_flag=True,
            pdf_flag=True,
        )

        class _FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "_FakeClient":
                return self

            async def __aexit__(self, *exc: Any) -> None:
                return None

            async def list_documents(self, target_date: date) -> list[DocumentMetadata]:
                if target_date == date.today():
                    return [annual]
                return []

            async def download(self, doc_id: str, *, content_type: str = "pdf") -> DocumentBody:
                if content_type == "xbrl_zip":
                    raise RuntimeError("xbrl 404")
                return _make_body(doc_id)

        monkeypatch.setattr(edinet_collector, "EdinetClient", _FakeClient)

        results = await edinet_collector.collect_filings("285A.T")
        # PDF 経路は維持される
        assert len(results) == 1
        assert results[0].financials is None

    @pytest.mark.asyncio
    async def test_xbrl_parse_with_no_tier1_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """parse_xbrl_zip が has_tier1_data=False を返したら financials は None。"""
        _stub_settings(
            monkeypatch,
            edinet_quarterly_lookback=0,
            edinet_search_window_days=3,
            edinet_enable_xbrl=True,
        )
        from agents import edinet_collector
        from edinet_client import XbrlFinancials

        annual = DocumentMetadata(
            document_id="A_EMPTY",
            edinet_code="E12345",
            securities_code="285A0",
            submitter_name="キオクシア",
            document_type=DocumentType.ANNUAL_REPORT,
            submit_date=date(2026, 5, 10),
            xbrl_flag=True,
            pdf_flag=True,
        )

        class _FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "_FakeClient":
                return self

            async def __aexit__(self, *exc: Any) -> None:
                return None

            async def list_documents(self, target_date: date) -> list[DocumentMetadata]:
                if target_date == date.today():
                    return [annual]
                return []

            async def download(self, doc_id: str, *, content_type: str = "pdf") -> DocumentBody:
                return _make_body(doc_id)

        # 全 None で has_tier1_data=False
        monkeypatch.setattr(edinet_collector, "EdinetClient", _FakeClient)
        monkeypatch.setattr(
            edinet_collector,
            "parse_xbrl_zip",
            lambda zip_bytes, *, document_id=None: XbrlFinancials(),
        )

        results = await edinet_collector.collect_filings("285A.T")
        assert len(results) == 1
        assert results[0].financials is None


class TestResolverBuild:
    def test_csv_loaded_correctly(self, tmp_path: Path) -> None:
        """テスト fixture の CSV が EdinetCodeResolver でパースできることを確認。"""
        csv_path = tmp_path / "Edinetcode.csv"
        csv_path.write_text(
            "ダウンロード日時：2026-05-23,,,,,,,,,,,,\n"
            "ＥＤＩＮＥＴコード,提出者種別,上場区分,連結の有無,資本金,決算日,"
            "提出者名,提出者名（英字）,提出者名（ヨミ）,所在地,提出者業種,証券コード,提出者法人番号\n"
            "E12345,内国法人・株式会社,上場,有,1000000000,3月31日,"
            "キオクシア,Kioxia,キオクシア,東京,電気機器,285A0,1234567890123\n",
            encoding="utf-8",
        )
        resolver = EdinetCodeResolver.from_csv_path(csv_path)
        assert resolver.resolve_edinet_code("285A.T") == "E12345"
