"""wayback_backfill_etl: 令和 4-6 年の入所結果 PDF を Wayback Machine 経由でバックフィル。

実行頻度 (proposal 0003 §4.5.4 表): **一度きり (Phase 0)**。
書き込み先: `admission_results` (令和 4-6 年) + `competition_stats.historical_minimum_index_2022`
利用先: 保活 Plan MCP のハイブリッドモデル (proposal 0005 §9.5)。

処理フロー:
  [1] 設定された `BackfillItem` のリストを順次処理
  [2] WaybackClient で `web.archive.org/web/{ts}/{url}` から PDF を取得
  [3] PdfArchive に原本保存 (proposal §4.5 line 204)
  [4] Docling で表抽出
  [5] kind ごとに parser を選択:
      - `regular`: `parse_admission_table` (令和 5-6 年の通常入所結果)
      - `min_index_2022`: `parse_min_index_table` (令和 4 年最低指数)
  [6] **(facility_id, year, round, age_class) で in-memory merge** してから AdmissionRepo に upsert
      (片方の PDF にしか値がないフィールドが None で上書きされるのを防ぐ)
  [7] `admission_results` に upsert (`min_*` 4 フィールドは令和 4 年のみ非 None)

注意:
- WaybackClient の polite ルール (5 秒間隔 + 503 retry) を尊重するため、
  `wayback_factory` で `async with` 互換のクライアントを生成して使う
- `competition_stats.historical_minimum_index_2022` の更新は `monthly_stats_compute`
  が次回実行時に行う (本 Job では admission_results に min_* を入れるだけ)
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from fujisawa_platform.crawler import WaybackClient, WaybackConfig, build_archive_url
from fujisawa_platform.etl._repos.admission import AdmissionResultRecord
from fujisawa_platform.etl._runner import EtlRunResult, run_etl_job
from fujisawa_platform.etl.admission_parser import parse_admission_table
from fujisawa_platform.etl.min_index_parser import parse_min_index_table
from fujisawa_platform.etl.pdf_archive import NullArchive, PdfArchive, archive_path
from fujisawa_platform.pdf_pipeline import PdfTable, extract_tables
from fujisawa_platform.resolver import FacilityResolver

if TYPE_CHECKING:  # pragma: no cover
    from fujisawa_platform.etl._repos.etl_runs import EtlRunsRepo


# wayback_backfill 内で扱う PDF の種類。
# - 'regular': 通常の入所結果 PDF (令和 5-6 年は全部こちら)
# - 'min_index_2022': 令和 4 年最低指数 PDF (`r4-4nyuusyonaiteisisuu.pdf`)
BackfillKind = Literal["regular", "min_index_2022"]

_ALLOWED_KINDS: tuple[str, ...] = ("regular", "min_index_2022")
_ALLOWED_ROUNDS: tuple[str, ...] = ("1st", "2nd")

_JOB_NAME = "wayback_backfill"


class BackfillItem(BaseModel):
    """1 PDF の取得情報。"""

    model_config = ConfigDict(frozen=True)

    kind: str = Field(description="'regular' または 'min_index_2022'")
    wayback_timestamp: str = Field(description="Wayback timestamp (YYYYMMDDhhmmss)")
    original_url: str = Field(description="元 PDF URL (web.archive.org にかけない)")
    year: int
    round: str  # '1st' / '2nd'

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in _ALLOWED_KINDS:
            raise ValueError(f"kind must be one of {_ALLOWED_KINDS}, got {v!r}")
        return v

    @field_validator("round")
    @classmethod
    def _round(cls, v: str) -> str:
        if v not in _ALLOWED_ROUNDS:
            raise ValueError(f"round must be one of {_ALLOWED_ROUNDS}, got {v!r}")
        return v

    @property
    def archive_url(self) -> str:
        """Wayback 経由の取得 URL。"""
        return build_archive_url(self.wayback_timestamp, self.original_url)


class _WaybackLike(Protocol):
    """`WaybackClient` の最小 protocol (テストで fake を入れやすくするため)。

    `fetch_bytes` は archive URL を直接受け取って bytes を返す薄いインターフェース。
    実 `WaybackClient` の場合は `fetch_archive(WaybackSnapshot)` をラップする。
    """

    async def __aenter__(self) -> _WaybackLike: ...
    async def __aexit__(self, *args: object) -> None: ...
    async def fetch_bytes(self, archive_url: str) -> bytes: ...


class _AdmissionRepoLike(Protocol):
    async def upsert_many(self, records: list[AdmissionResultRecord]) -> int: ...


TableExtractor = Callable[[bytes], list[PdfTable]]
WaybackFactory = Callable[[WaybackConfig], _WaybackLike]


class WaybackBackfillOutcome(BaseModel):
    """`backfill_admissions` の戻り値。"""

    model_config = ConfigDict(frozen=True)

    items_processed: int = 0
    records_upserted: int = 0
    archive_paths: list[str] = []


async def backfill_admissions(
    *,
    items: list[BackfillItem],
    wayback: _WaybackLike,
    admission_repo: _AdmissionRepoLike,
    resolver: FacilityResolver,
    archive: PdfArchive | None = None,
    table_extractor: TableExtractor | None = None,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> WaybackBackfillOutcome:
    """Wayback Machine 経由で複数 PDF を取得して admission_results にバックフィル。

    Args:
        items: 取得対象の PDF 一覧 (kind / timestamp / url / year / round)。
        wayback: `WaybackClient` 互換オブジェクト (`async with` 済の前提)。
        admission_repo: `AdmissionRepo` (DI 可能)。
        resolver: 施設名 → facility_id 解決用 (build_facility_resolver で構築)。
        archive: PDF アーカイブ先 (default は `NullArchive`)。
        table_extractor: 表抽出関数 (default: `pdf_pipeline.extract_tables`)。
            テストでは mock を注入可能。
        now: 任意。as_of の差し替え (テスト用)。
        dry_run: True なら parse / archive は行うが repo.upsert_many を呼ばない。
    """
    _now = now or _utcnow
    _archive: PdfArchive = archive or NullArchive()
    _extract = table_extractor or extract_tables
    as_of = _now()

    # in-memory マージ用辞書: (facility_id, year, round, age_class) → AdmissionResultRecord
    merged: dict[tuple[str, int, str, int], AdmissionResultRecord] = {}
    archive_paths: list[str] = []

    for item in items:
        if item.kind not in _ALLOWED_KINDS:
            raise ValueError(f"unknown kind: {item.kind!r}")

        # [2] Wayback fetch
        pdf_bytes = await wayback.fetch_bytes(item.archive_url)

        # [3] アーカイブ
        destination = archive_path(
            job_name=_JOB_NAME,
            url=item.original_url,
            year=item.year,
            round=item.round,
        )
        put_result = await _archive.put(
            path=destination,
            content=pdf_bytes,
            source_url=item.archive_url,
            fetched_at=as_of,
        )
        archive_paths.append(put_result.path)

        # [4][5] Docling で表抽出 → kind 別に parser を選ぶ
        tables = _extract(pdf_bytes)

        if item.kind == "regular":
            for table in tables:
                for rec in parse_admission_table(
                    table=table,
                    year=item.year,
                    round=item.round,
                    source_pdf_url=item.archive_url,
                    as_of=as_of,
                    resolver=resolver,
                ):
                    _merge_regular(merged, rec)
        elif item.kind == "min_index_2022":
            for table in tables:
                for entry in parse_min_index_table(
                    table=table,
                    source_pdf_url=item.archive_url,
                    resolver=resolver,
                ):
                    _merge_min_index(
                        merged,
                        entry=entry,
                        year=item.year,
                        round=item.round,
                        as_of=as_of,
                    )

    # [6][7] AdmissionRepo に upsert
    records = list(merged.values())
    if not dry_run and records:
        await admission_repo.upsert_many(records)

    return WaybackBackfillOutcome(
        items_processed=len(items),
        records_upserted=len(records),
        archive_paths=archive_paths,
    )


async def run_wayback_backfill(
    *,
    items: list[BackfillItem],
    wayback_config: WaybackConfig,
    admission_repo: _AdmissionRepoLike,
    runs_repo: EtlRunsRepo,
    resolver: FacilityResolver,
    run_id: str,
    archive: PdfArchive | None = None,
    wayback_factory: WaybackFactory | None = None,
    table_extractor: TableExtractor | None = None,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> EtlRunResult:
    """Cloud Run Job のエントリポイント (run_etl_job ラップ)。

    `wayback_factory` で `WaybackClient` 互換オブジェクトを生成可能 (テストでは fake を注入)。
    default は `_default_wayback_factory` で実 `WaybackClient` を使う。
    """
    factory: WaybackFactory = wayback_factory or _default_wayback_factory

    async def _job() -> EtlRunResult:
        wayback = factory(wayback_config)
        async with wayback as client:
            outcome = await backfill_admissions(
                items=items,
                wayback=client,
                admission_repo=admission_repo,
                resolver=resolver,
                archive=archive,
                table_extractor=table_extractor,
                now=now,
                dry_run=dry_run,
            )
        return EtlRunResult(
            rows_written=outcome.records_upserted,
            source_url=None,
            source_hash=None,
            status="success",
        )

    return await run_etl_job(
        job_name=_JOB_NAME,
        run_id=run_id,
        repo=runs_repo,
        fn=_job,
        now=now,
    )


# ─────────────────────────────────────────────────────────────────────
# Merge helpers (in-memory join of regular + min_index by composite key)
# ─────────────────────────────────────────────────────────────────────


def _merge_regular(
    merged: dict[tuple[str, int, str, int], AdmissionResultRecord],
    rec: AdmissionResultRecord,
) -> None:
    """regular PDF のレコードをマージ (既存の min_* を保持)。"""
    key = (rec.facility_id, rec.year, rec.round, rec.age_class)
    existing = merged.get(key)
    if existing is None:
        merged[key] = rec
    else:
        merged[key] = existing.model_copy(
            update={
                "applicants_at_deadline": rec.applicants_at_deadline,
                "capacity": rec.capacity,
                "vacancy_after": rec.vacancy_after,
                "source_pdf_url": rec.source_pdf_url,
                "as_of": rec.as_of,
            }
        )


def _merge_min_index(
    merged: dict[tuple[str, int, str, int], AdmissionResultRecord],
    *,
    entry: object,
    year: int,
    round: str,
    as_of: datetime,
) -> None:
    """`MinIndexEntry` をマージ (既存の applicants / capacity は保持)。

    `entry` 型は `min_index_parser.MinIndexEntry` だが、import 循環を避けるため
    `object` で受け、属性アクセスで取り出す。
    """
    facility_id = getattr(entry, "facility_id")
    age_class = getattr(entry, "age_class")
    basic = getattr(entry, "basic")
    priority = getattr(entry, "priority")
    coord = getattr(entry, "coord")
    notation = getattr(entry, "notation")
    source_pdf_url = getattr(entry, "source_pdf_url")

    key = (facility_id, year, round, age_class)
    existing = merged.get(key)
    if existing is None:
        merged[key] = AdmissionResultRecord(
            facility_id=facility_id,
            year=year,
            round=round,
            age_class=age_class,
            applicants_at_deadline=None,
            capacity=None,
            vacancy_after=None,
            min_basic_score=basic,
            min_priority=priority,
            min_coordination_score=coord,
            min_index_notation=notation,
            source_pdf_url=source_pdf_url,
            as_of=as_of,
        )
    else:
        merged[key] = existing.model_copy(
            update={
                "min_basic_score": basic,
                "min_priority": priority,
                "min_coordination_score": coord,
                "min_index_notation": notation,
            }
        )


# ─────────────────────────────────────────────────────────────────────
# Default factory + utilities
# ─────────────────────────────────────────────────────────────────────


def _default_wayback_factory(config: WaybackConfig) -> _WaybackLike:
    """本番用 factory: 実 `WaybackClient` を生成し、archive URL から bytes を取り出す。

    本 Job は archive URL を直接組み立てるので、CDX query は通らず、
    Wayback の `fetch_archive(WaybackSnapshot)` を URL ベースで使い回す薄いラッパー。
    """
    return _WaybackBytesAdapter(WaybackClient(config))


class _WaybackBytesAdapter:
    """`WaybackClient` を `fetch_bytes(archive_url)` インターフェースに合わせるアダプタ。"""

    def __init__(self, client: WaybackClient) -> None:
        self._client = client

    async def __aenter__(self) -> _WaybackBytesAdapter:
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._client.__aexit__(*args)  # type: ignore[arg-type]

    async def fetch_bytes(self, archive_url: str) -> bytes:
        # `WaybackClient._request_with_retry` は private なので、`fetch_archive` 経由で
        # 一時 snapshot を作ってもよい。シンプルにここで _client の内部を直接叩く。
        # protocol breaking を避けるため、内部 client を re-use する。
        return await _fetch_via_client(self._client, archive_url)


async def _fetch_via_client(client: WaybackClient, archive_url: str) -> bytes:
    """`WaybackClient._get_bytes_with_retry` を呼び出す薄いラッパー。

    内部 API のため、型 ignore でアクセス。Phase 3 の `WaybackClient.fetch_archive`
    は `WaybackSnapshot` 型を要求するが、ここでは URL を直接渡したいので内部メソッドを使う。
    """
    return await client._get_bytes_with_retry(archive_url)  # type: ignore[attr-defined]


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "BackfillItem",
    "BackfillKind",
    "TableExtractor",
    "WaybackBackfillOutcome",
    "WaybackFactory",
    "backfill_admissions",
    "run_wayback_backfill",
]
