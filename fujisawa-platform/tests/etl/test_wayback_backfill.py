"""wayback_backfill_etl のテスト (Phase 4-2g、一度きり実行)。

WaybackClient + admission_parser + min_index_parser + PdfArchive を組み合わせ、
過去 PDF を順に取得 → アーカイブ → 解析 → 統合 → admission_results にマージ upsert する。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fujisawa_platform.crawler import WaybackConfig
from fujisawa_platform.etl._repos.admission import AdmissionResultRecord
from fujisawa_platform.etl._runner import EtlRunResult
from fujisawa_platform.etl.pdf_archive import ArchivePut
from fujisawa_platform.etl.wayback_backfill import (
    BackfillItem,
    WaybackBackfillOutcome,
    backfill_admissions,
    run_wayback_backfill,
)
from fujisawa_platform.pdf_pipeline import PdfTable
from fujisawa_platform.resolver import FacilityResolver, ResolverEntry

_NOW = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)


# ─────────────────────────────────────────────────────────────────────
# Fakes / stubs
# ─────────────────────────────────────────────────────────────────────


class _FakeWaybackClient:
    """WaybackClient の振る舞い fake (実 HTTP は叩かない)。

    `pdf_bytes_by_url` で URL → bytes のマッピングを与え、`fetch_archive` は
    対応する bytes を返す。`async with` プロトコルも実装。
    """

    def __init__(self, pdf_bytes_by_url: dict[str, bytes]) -> None:
        self._pdf = pdf_bytes_by_url
        self.fetched: list[str] = []

    async def __aenter__(self) -> _FakeWaybackClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def fetch_bytes(self, archive_url: str) -> bytes:
        self.fetched.append(archive_url)
        return self._pdf.get(archive_url, b"%PDF-default")


class _RecordingAdmissionRepo:
    def __init__(self) -> None:
        self.upserts: list[list[AdmissionResultRecord]] = []

    async def upsert_many(self, records: list[AdmissionResultRecord]) -> int:
        self.upserts.append(list(records))
        return len(records)


class _RecordingArchive:
    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []

    async def put(
        self,
        *,
        path: str,
        content: bytes,
        source_url: str,
        fetched_at: datetime,
    ) -> ArchivePut:
        self.puts.append(
            {"path": path, "content": content, "source_url": source_url, "fetched_at": fetched_at}
        )
        return ArchivePut(backend="fake", path=path)

    async def get(self, path: str) -> bytes:
        return next(p["content"] for p in self.puts if p["path"] == path)

    async def exists(self, path: str) -> bool:
        return any(p["path"] == path for p in self.puts)


class _FakeRunsRepo:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        self.finishes: list[dict[str, Any]] = []

    async def start_run(self, **kwargs: Any) -> None:
        self.starts.append(kwargs)

    async def finish_run(self, **kwargs: Any) -> None:
        self.finishes.append(kwargs)

    async def recent_runs(self, job_name: str, *, limit: int = 5) -> list[Any]:
        return []


def _resolver() -> FacilityResolver:
    return FacilityResolver(
        [
            ResolverEntry(facility_id="kouritsu-aaa", canonical_name="藤沢保育園"),
            ResolverEntry(facility_id="kouritsu-bbb", canonical_name="辻堂保育園"),
        ]
    )


def _admission_table() -> PdfTable:
    """通常の入所結果 PDF の表 (admission_parser 互換)。"""
    return PdfTable(
        headers=[
            "施設名",
            "0歳児定員",
            "0歳児申込",
            "0歳児利用枠",
        ],
        rows=[
            ["藤沢保育園", "12", "30", "0"],
            ["辻堂保育園", "9", "15", "0"],
        ],
    )


def _min_index_table() -> PdfTable:
    """令和 4 年最低指数 PDF の表 (min_index_parser 互換)。"""
    return PdfTable(
        headers=["施設名", "0歳児", "1歳児"],
        rows=[
            ["藤沢保育園", "10F11", "△"],
            ["辻堂保育園", "9F8", "8E12"],
        ],
    )


# ─────────────────────────────────────────────────────────────────────
# backfill_admissions (本丸)
# ─────────────────────────────────────────────────────────────────────


class TestBackfillAdmissions:
    @pytest.mark.asyncio
    async def test_regular_pdf_only_upserts_basic_fields(self) -> None:
        items = [
            BackfillItem(
                kind="regular",
                wayback_timestamp="20230401000000",
                original_url="https://www.city.fujisawa.kanagawa.jp/r5.pdf",
                year=2023,
                round="1st",
            ),
        ]
        archive_url = (
            "https://web.archive.org/web/20230401000000/"
            "https://www.city.fujisawa.kanagawa.jp/r5.pdf"
        )
        wb = _FakeWaybackClient({archive_url: b"%PDF-r5"})
        admission_repo = _RecordingAdmissionRepo()

        outcome = await backfill_admissions(
            items=items,
            wayback=wb,  # type: ignore[arg-type]
            admission_repo=admission_repo,  # type: ignore[arg-type]
            resolver=_resolver(),
            archive=None,
            table_extractor=lambda _: [_admission_table()],
            now=lambda: _NOW,
        )

        # 2 施設 × 1 age_class = 2 件
        assert outcome.records_upserted == 2
        records = admission_repo.upserts[0]
        for r in records:
            assert r.year == 2023
            assert r.round == "1st"
            assert r.min_basic_score is None  # min_index は無い
            assert r.min_priority is None

    @pytest.mark.asyncio
    async def test_min_index_only_does_not_overwrite_with_none(self) -> None:
        """`min_index_2022` 単独の場合、applicants / capacity は None で記録される。

        実運用では regular PDF と組み合わせて使うが、parser 単独でも壊れないこと。
        """
        items = [
            BackfillItem(
                kind="min_index_2022",
                wayback_timestamp="20220308000000",
                original_url="https://www.city.fujisawa.kanagawa.jp/r4-min.pdf",
                year=2022,
                round="1st",
            ),
        ]
        archive_url = (
            "https://web.archive.org/web/20220308000000/"
            "https://www.city.fujisawa.kanagawa.jp/r4-min.pdf"
        )
        wb = _FakeWaybackClient({archive_url: b"%PDF-r4min"})
        admission_repo = _RecordingAdmissionRepo()

        outcome = await backfill_admissions(
            items=items,
            wayback=wb,  # type: ignore[arg-type]
            admission_repo=admission_repo,  # type: ignore[arg-type]
            resolver=_resolver(),
            table_extractor=lambda _: [_min_index_table()],
            now=lambda: _NOW,
        )

        # 藤沢 0歳児 + 辻堂 0歳児 + 辻堂 1歳児 = 3 件
        assert outcome.records_upserted == 3
        records = admission_repo.upserts[0]
        for r in records:
            assert r.year == 2022
            assert r.round == "1st"
            # 通常データなし
            assert r.applicants_at_deadline is None
            assert r.capacity is None
            # min_index データあり
            assert r.min_basic_score is not None
            assert r.min_priority is not None

    @pytest.mark.asyncio
    async def test_combines_regular_and_min_index_for_same_key(self) -> None:
        """regular PDF と min_index PDF が同じ (facility, year, round, age) を持つ場合、
        merge して 1 行に統合する (片方を None で上書きしない)。
        """
        items = [
            BackfillItem(
                kind="regular",
                wayback_timestamp="20220308000000",
                original_url="https://www.city.fujisawa.kanagawa.jp/r4-regular.pdf",
                year=2022,
                round="1st",
            ),
            BackfillItem(
                kind="min_index_2022",
                wayback_timestamp="20220308000000",
                original_url="https://www.city.fujisawa.kanagawa.jp/r4-min.pdf",
                year=2022,
                round="1st",
            ),
        ]
        archive_regular = (
            "https://web.archive.org/web/20220308000000/"
            "https://www.city.fujisawa.kanagawa.jp/r4-regular.pdf"
        )
        archive_min = (
            "https://web.archive.org/web/20220308000000/"
            "https://www.city.fujisawa.kanagawa.jp/r4-min.pdf"
        )
        wb = _FakeWaybackClient({archive_regular: b"%PDF-r4r", archive_min: b"%PDF-r4m"})
        admission_repo = _RecordingAdmissionRepo()

        def extractor(content: bytes) -> list[PdfTable]:
            if content == b"%PDF-r4r":
                return [_admission_table()]
            return [_min_index_table()]

        outcome = await backfill_admissions(
            items=items,
            wayback=wb,  # type: ignore[arg-type]
            admission_repo=admission_repo,  # type: ignore[arg-type]
            resolver=_resolver(),
            table_extractor=extractor,
            now=lambda: _NOW,
        )

        # 藤沢: 0 歳児に regular + min_index 両方 / 辻堂: 0歳児に両方 + 1歳児に min_index のみ
        # = 3 件
        assert outcome.records_upserted == 3
        records = admission_repo.upserts[0]
        by_key = {(r.facility_id, r.age_class): r for r in records}

        # 藤沢 0歳児: 両方データあり
        fuji_0 = by_key[("kouritsu-aaa", 0)]
        assert fuji_0.applicants_at_deadline == 30
        assert fuji_0.capacity == 12
        assert fuji_0.min_basic_score == 10
        assert fuji_0.min_priority == "F"
        assert fuji_0.min_coordination_score == 11
        assert fuji_0.min_index_notation == "10F11"

        # 辻堂 0歳児: 両方データあり
        tuji_0 = by_key[("kouritsu-bbb", 0)]
        assert tuji_0.applicants_at_deadline == 15
        assert tuji_0.min_basic_score == 9

        # 辻堂 1歳児: min_index のみ
        tuji_1 = by_key[("kouritsu-bbb", 1)]
        assert tuji_1.applicants_at_deadline is None
        assert tuji_1.min_basic_score == 8

    @pytest.mark.asyncio
    async def test_archive_called_for_each_pdf(self) -> None:
        """各 PDF が archive.put される。"""
        items = [
            BackfillItem(
                kind="regular",
                wayback_timestamp="20220308000000",
                original_url="https://x/a.pdf",
                year=2022,
                round="1st",
            ),
            BackfillItem(
                kind="regular",
                wayback_timestamp="20230401000000",
                original_url="https://x/b.pdf",
                year=2023,
                round="1st",
            ),
        ]
        wb = _FakeWaybackClient(
            {
                "https://web.archive.org/web/20220308000000/https://x/a.pdf": b"%PDF-a",
                "https://web.archive.org/web/20230401000000/https://x/b.pdf": b"%PDF-b",
            }
        )
        archive = _RecordingArchive()

        await backfill_admissions(
            items=items,
            wayback=wb,  # type: ignore[arg-type]
            admission_repo=_RecordingAdmissionRepo(),  # type: ignore[arg-type]
            resolver=_resolver(),
            archive=archive,  # type: ignore[arg-type]
            table_extractor=lambda _: [_admission_table()],
            now=lambda: _NOW,
        )

        assert len(archive.puts) == 2
        paths = {p["path"] for p in archive.puts}
        # 各 PDF が wayback_backfill/{year}/{round}/ 配下に保存される
        assert all(p.startswith("wayback_backfill/") for p in paths)
        # 同じバケットだが path は別 (URL が異なるため)
        assert len(paths) == 2

    @pytest.mark.asyncio
    async def test_dry_run_does_not_upsert(self) -> None:
        items = [
            BackfillItem(
                kind="regular",
                wayback_timestamp="20230401000000",
                original_url="https://x/a.pdf",
                year=2023,
                round="1st",
            ),
        ]
        wb = _FakeWaybackClient(
            {"https://web.archive.org/web/20230401000000/https://x/a.pdf": b"%PDF-a"}
        )
        admission_repo = _RecordingAdmissionRepo()

        outcome = await backfill_admissions(
            items=items,
            wayback=wb,  # type: ignore[arg-type]
            admission_repo=admission_repo,  # type: ignore[arg-type]
            resolver=_resolver(),
            table_extractor=lambda _: [_admission_table()],
            dry_run=True,
        )

        assert outcome.records_upserted == 2  # parse 件数
        assert admission_repo.upserts == []  # DB 未書き込み

    def test_unknown_kind_rejected_at_construction(self) -> None:
        """BackfillItem 構築段階で kind は Pydantic validator で検証される。"""
        with pytest.raises(ValueError, match="kind"):
            BackfillItem(
                kind="unknown",
                wayback_timestamp="20230401000000",
                original_url="https://x/a.pdf",
                year=2023,
                round="1st",
            )

    @pytest.mark.asyncio
    async def test_empty_items_returns_zero(self) -> None:
        outcome = await backfill_admissions(
            items=[],
            wayback=_FakeWaybackClient({}),  # type: ignore[arg-type]
            admission_repo=_RecordingAdmissionRepo(),  # type: ignore[arg-type]
            resolver=_resolver(),
            table_extractor=lambda _: [],
        )
        assert outcome.records_upserted == 0
        assert outcome.items_processed == 0


# ─────────────────────────────────────────────────────────────────────
# run_wayback_backfill (Cloud Run Job entrypoint)
# ─────────────────────────────────────────────────────────────────────


class TestRunWaybackBackfill:
    @pytest.mark.asyncio
    async def test_returns_success(self) -> None:
        items = [
            BackfillItem(
                kind="regular",
                wayback_timestamp="20230401000000",
                original_url="https://x/a.pdf",
                year=2023,
                round="1st",
            ),
        ]
        wb = _FakeWaybackClient(
            {"https://web.archive.org/web/20230401000000/https://x/a.pdf": b"%PDF-a"}
        )
        runs = _FakeRunsRepo()

        result = await run_wayback_backfill(
            items=items,
            wayback_config=WaybackConfig(user_agent="fujisawa-etl-test/0.1 (https://example.com)"),
            admission_repo=_RecordingAdmissionRepo(),  # type: ignore[arg-type]
            runs_repo=runs,  # type: ignore[arg-type]
            resolver=_resolver(),
            run_id="wayback_backfill-20260512-0300",
            wayback_factory=lambda _: wb,  # type: ignore[arg-type]
            table_extractor=lambda _: [_admission_table()],
            now=lambda: _NOW,
        )

        assert isinstance(result, EtlRunResult)
        assert result.status == "success"
        assert result.rows_written == 2
        assert runs.finishes[0]["status"] == "success"


# ─────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────


class TestBackfillItem:
    def test_kind_validation(self) -> None:
        with pytest.raises(ValueError, match="kind"):
            BackfillItem(
                kind="bad",
                wayback_timestamp="20230401000000",
                original_url="https://x/a.pdf",
                year=2023,
                round="1st",
            )

    def test_round_validation(self) -> None:
        with pytest.raises(ValueError, match="round"):
            BackfillItem(
                kind="regular",
                wayback_timestamp="20230401000000",
                original_url="https://x/a.pdf",
                year=2023,
                round="3rd",
            )


class TestOutcomeModel:
    def test_frozen(self) -> None:
        outcome = WaybackBackfillOutcome(
            items_processed=3,
            records_upserted=15,
            archive_paths=["wayback_backfill/2022/1st/aaa.pdf"],
        )
        with pytest.raises(Exception):
            outcome.records_upserted = 99  # type: ignore[misc]
