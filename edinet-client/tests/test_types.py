"""Pydantic 型のテスト。"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from edinet_client import (
    DisclosureStatus,
    DocumentBody,
    DocumentMetadata,
    DocumentType,
    WithdrawalStatus,
)


class TestDocumentType:
    def test_known_codes_resolve(self) -> None:
        assert DocumentType("120") == DocumentType.ANNUAL_REPORT
        assert DocumentType("140") == DocumentType.QUARTERLY_REPORT
        assert DocumentType("350") == DocumentType.MAJOR_HOLDING
        assert DocumentType("490") == DocumentType.TENDER_OFFER

    def test_unknown_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            DocumentType("999")

    def test_str_value_matches_code(self) -> None:
        assert DocumentType.ANNUAL_REPORT.value == "120"


class TestStatusEnums:
    def test_withdrawal_status_values(self) -> None:
        assert WithdrawalStatus.ACTIVE.value == "0"
        assert WithdrawalStatus.WITHDRAWN.value == "1"

    def test_disclosure_status_values(self) -> None:
        assert DisclosureStatus.DISCLOSED.value == "0"
        assert DisclosureStatus.STOPPED.value == "1"
        assert DisclosureStatus.CANCELLED.value == "2"


class TestDocumentMetadata:
    def test_minimal_construct(self) -> None:
        doc = DocumentMetadata(
            document_id="S100ABC1",
            edinet_code="E02144",
            submitter_name="トヨタ自動車",
            document_type=DocumentType.ANNUAL_REPORT,
            submit_date=date(2026, 5, 22),
        )
        assert doc.document_id == "S100ABC1"
        assert doc.is_available is True

    def test_withdrawn_not_available(self) -> None:
        doc = DocumentMetadata(
            document_id="S100ABC1",
            edinet_code="E02144",
            submitter_name="X",
            document_type=DocumentType.MAJOR_HOLDING,
            submit_date=date(2026, 5, 22),
            withdrawal_status=1,
        )
        assert doc.is_available is False

    def test_disclosure_stopped_not_available(self) -> None:
        doc = DocumentMetadata(
            document_id="S100ABC1",
            edinet_code="E02144",
            submitter_name="X",
            document_type=DocumentType.ANNUAL_REPORT,
            submit_date=date(2026, 5, 22),
            disclosure_status=1,
        )
        assert doc.is_available is False

    def test_frozen(self) -> None:
        doc = DocumentMetadata(
            document_id="S100ABC1",
            edinet_code="E02144",
            submitter_name="X",
            document_type=DocumentType.ANNUAL_REPORT,
            submit_date=date(2026, 5, 22),
        )
        with pytest.raises(Exception):
            doc.document_id = "X"  # type: ignore[misc]


class TestDocumentBody:
    def test_construct(self) -> None:
        body = DocumentBody(
            document_id="S100ABC1",
            content_type="pdf",
            bytes_payload=b"%PDF-1.4",
            fetched_at=datetime.now(UTC),
            from_cache=False,
        )
        assert body.document_id == "S100ABC1"
        assert body.bytes_payload == b"%PDF-1.4"
        assert body.from_cache is False

    def test_bytes_payload_not_in_repr(self) -> None:
        body = DocumentBody(
            document_id="S100ABC1",
            content_type="pdf",
            bytes_payload=b"X" * 1000,
            fetched_at=datetime.now(UTC),
            from_cache=False,
        )
        # repr に巨大な bytes を含めない (Field(repr=False))
        assert "X" * 100 not in repr(body)
