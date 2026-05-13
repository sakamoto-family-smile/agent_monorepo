"""`wayback_items.RUNTIME_ITEMS` の構造と不変条件のテスト (Phase 4-2h step 3-2)。

CDX で実 URL / timestamp を確定した上で hardcode しているため、
意図しない変更 (URL typo / timestamp 桁数ミス) を検知する garde rail として機能する。
"""

from __future__ import annotations

import pytest

from fujisawa_platform.etl.wayback_backfill import BackfillItem
from fujisawa_platform.etl.wayback_items import RUNTIME_ITEMS


class TestRuntimeItems:
    def test_is_tuple(self) -> None:
        """順序固定の不変コンテナ (tuple) であること。"""
        assert isinstance(RUNTIME_ITEMS, tuple)

    def test_only_r4_min_index_for_now(self) -> None:
        """現状は令和 4 年 (2022) min_index PDF 1 件のみ。

        追加収録する場合は本テストも更新する (意図しない追加を検知)。
        """
        assert len(RUNTIME_ITEMS) == 1

    def test_r4_min_index_item_fields(self) -> None:
        """r4-4nyuusyonaiteisisuu.pdf の BackfillItem が CDX 由来の値で固定。

        CDX 確認時 (2026-05-13):
          - timestamp: 20220308001221
          - original_url: city.fujisawa.kanagawa.jp/hoiku/documents/r4-4nyuusyonaiteisisuu.pdf
          - 184,967 bytes / application/pdf / status 200
        """
        item = RUNTIME_ITEMS[0]
        assert item.kind == "min_index_2022"
        assert item.wayback_timestamp == "20220308001221"
        assert item.original_url == (
            "https://www.city.fujisawa.kanagawa.jp/hoiku/documents/"
            "r4-4nyuusyonaiteisisuu.pdf"
        )
        assert item.year == 2022
        assert item.round == "1st"

    def test_archive_url_resolves(self) -> None:
        """`build_archive_url` 経由で archive URL が生成できる。"""
        item = RUNTIME_ITEMS[0]
        url = item.archive_url
        assert url.startswith("https://web.archive.org/web/20220308001221/")
        assert url.endswith("r4-4nyuusyonaiteisisuu.pdf")

    def test_items_are_frozen(self) -> None:
        """`BackfillItem` は frozen (Pydantic ConfigDict(frozen=True))。"""
        item = RUNTIME_ITEMS[0]
        with pytest.raises(Exception):  # ValidationError or FrozenInstanceError 系
            item.year = 2099  # type: ignore[misc]

    def test_all_items_valid_backfill_item(self) -> None:
        """全 item が `BackfillItem` instance。"""
        for item in RUNTIME_ITEMS:
            assert isinstance(item, BackfillItem)
