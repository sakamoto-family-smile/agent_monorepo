"""FreshnessMetadata のテスト。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from fujisawa_platform.models import FreshnessMetadata


class TestFreshnessMetadata:
    def test_minimum_required_fields(self) -> None:
        """as_of と source_url のみで生成可能。"""
        meta = FreshnessMetadata(
            as_of=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
            source_url="https://www.city.fujisawa.kanagawa.jp/",
        )
        assert meta.source_pdf_url is None
        assert meta.snapshot_date is None
        assert meta.etl_job_id is None
        assert meta.schema_version == "v1"

    def test_full_fields_for_pdf_source(self) -> None:
        """PDF 由来データは pdf_url + snapshot_date を埋める。"""
        meta = FreshnessMetadata(
            as_of=datetime(2026, 1, 22, 3, 15, tzinfo=UTC),
            source_url="https://www.city.fujisawa.kanagawa.jp/hoiku/.../nyushojokyo.html",
            source_pdf_url="https://www.city.fujisawa.kanagawa.jp/documents/9848/20260115092454.pdf",
            snapshot_date=date(2026, 1, 20),
            etl_job_id="vacancy_etl-20260122-0300",
            schema_version="v1.2",
        )
        assert str(meta.source_pdf_url).endswith(".pdf")
        assert meta.snapshot_date == date(2026, 1, 20)
        assert meta.etl_job_id == "vacancy_etl-20260122-0300"
        assert meta.schema_version == "v1.2"

    def test_immutable(self) -> None:
        """frozen=True なので変更不可。"""
        meta = FreshnessMetadata(
            as_of=datetime(2026, 5, 9, tzinfo=UTC),
            source_url="https://www.city.fujisawa.kanagawa.jp/",
        )
        with pytest.raises(ValidationError):
            meta.schema_version = "v2"  # type: ignore[misc]

    def test_invalid_url_rejected(self) -> None:
        """非 URL は弾く (引用に使えないため)。"""
        with pytest.raises(ValidationError):
            FreshnessMetadata(
                as_of=datetime(2026, 5, 9, tzinfo=UTC),
                source_url="not-a-url",
            )

    def test_days_since_returns_elapsed_days(self) -> None:
        """as_of から N 日経過していれば N を返す。"""
        meta = FreshnessMetadata(
            as_of=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            source_url="https://www.city.fujisawa.kanagawa.jp/",
        )
        # 14 日 12 時間後の time
        now = datetime(2026, 1, 16, 0, 0, tzinfo=UTC)
        assert meta.days_since(now=now) == 14

    def test_days_since_floors_partial_days(self) -> None:
        """1 日未満は 0 として扱う (timedelta.days と同じ仕様)。"""
        meta = FreshnessMetadata(
            as_of=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            source_url="https://www.city.fujisawa.kanagawa.jp/",
        )
        now = datetime(2026, 1, 1, 23, 59, tzinfo=UTC)
        assert meta.days_since(now=now) == 0

    def test_days_since_clamps_future_to_zero(self) -> None:
        """未来日付の as_of は 0 を返す (時刻ズレ等で発生し得る)。"""
        meta = FreshnessMetadata(
            as_of=datetime(2026, 12, 31, tzinfo=UTC),
            source_url="https://www.city.fujisawa.kanagawa.jp/",
        )
        now = datetime(2026, 1, 1, tzinfo=UTC)
        assert meta.days_since(now=now) == 0

    def test_days_since_uses_utc_now_by_default(self) -> None:
        """`now` 省略時は現在時刻基準。"""
        meta = FreshnessMetadata(
            as_of=datetime.now(UTC) - timedelta(days=3),
            source_url="https://www.city.fujisawa.kanagawa.jp/",
        )
        assert meta.days_since() == 3
