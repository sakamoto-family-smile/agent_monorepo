"""half_yearly_facility_etl: 認可・認可外保育施設マスタ更新 Job (proposal 0003 §4.5.4)。

実行頻度: 4 月・10 月 1 日 03:00 JST、Cloud Run Job として配備。

処理フロー:
  [1] 認可施設一覧 HTML を polite fetch
  [2] 認可外施設一覧 HTML を polite fetch
  [3] 各 HTML から `<table>` を抽出 + 行ごとのリンク URL を取得
  [4] 認可: facility_type ごとに parse_authorized_table
  [5] 認可外: parse_unauthorized_table (括弧内類型 + 駅徒歩分数を抽出)
  [6] FacilitiesRepo.replace_all で全削除→全 INSERT (1 トランザクション)

書き込み先テーブル: `facilities` (~160 件)
利用先: 保活 SearchAgent (proposal 0005)。

整合性 (proposal 0003 §4.5.5):
- 半年に 1 回しか走らない、件数が小さい (~160) ため、全削除→全 INSERT で十分。
- consumer 側は SELECT 失敗時に tenacity retry で吸収する想定。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

from fujisawa_platform.crawler import FetchResult, NotModified, PoliteFetcher, PoliteFetcherConfig
from fujisawa_platform.etl._html_table import HtmlTable, extract_tables_with_links
from fujisawa_platform.etl._repos.facilities import FacilityRecord
from fujisawa_platform.etl._runner import EtlRunResult, run_etl_job
from fujisawa_platform.etl.facility_parser import (
    parse_authorized_table,
    parse_unauthorized_table,
)

if TYPE_CHECKING:  # pragma: no cover
    from fujisawa_platform.etl._repos.etl_runs import EtlRunsRepo

# 認可 HTML 内のテーブル順 → facility_type の対応 (proposal 0003 §A4-1 / 調査ノート §A4-1)。
# 5 テーブルを期待: 公立 / 法人等 / 認定こども園 / 小規模 / 家庭的。
# テーブル数が想定と異なる場合は parsable な範囲だけ処理し、不足分は無視する
# (将来 HTML 構造が変わった場合のフォールバック)。
_AUTHORIZED_TABLE_TYPES: list[str] = [
    "公立保育所",
    "法人等保育所",
    "認定こども園",
    "小規模保育事業",
    "家庭的保育事業",
]


class _FacilitiesRepoLike(Protocol):
    async def replace_all(self, records: list[FacilityRecord]) -> int: ...


class FacilityCrawlOutcome(BaseModel):
    """`crawl_and_replace_facilities` の戻り値。

    `run_half_yearly_facility` ラッパーが `EtlRunResult` に変換する。
    """

    model_config = ConfigDict(frozen=True)

    rows_written: int = 0
    skipped_empty_rows: int = 0
    authorized_hash: str | None = None
    unauthorized_hash: str | None = None


async def crawl_and_replace_facilities(
    *,
    authorized_url: str,
    unauthorized_url: str,
    fetcher: PoliteFetcher,
    repo: _FacilitiesRepoLike,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> FacilityCrawlOutcome:
    """認可 + 認可外 HTML を取得し、`facilities` を全置換する。

    Args:
        authorized_url: 認可施設一覧 HTML の URL。
        unauthorized_url: 認可外施設一覧 HTML の URL。
        fetcher: PoliteFetcher (consumer 側で `async with` 済のもの)。
        repo: `FacilitiesRepo` (DI 可能)。
        now: 任意。as_of の差し替え (テスト用)。
        dry_run: True なら parse は行うが repo.replace_all は呼ばない。
    """
    _now = now or _utcnow
    as_of = _now()

    auth_html, auth_hash = await _fetch_text(fetcher, authorized_url)
    unauth_html, unauth_hash = await _fetch_text(fetcher, unauthorized_url)

    records: list[FacilityRecord] = []

    # [4] 認可: テーブル順に facility_type を割り当て
    auth_tables = extract_tables_with_links(auth_html)
    for table, facility_type in zip(auth_tables, _AUTHORIZED_TABLE_TYPES, strict=False):
        records.extend(
            parse_authorized_table(
                table=table,
                facility_type=facility_type,
                source_url=authorized_url,
                as_of=as_of,
            )
        )

    # [5] 認可外: 全テーブルを単一の解析に流す (駅エリア別 4 テーブルがあるが
    # 全部 parse_unauthorized_table の入力形式は同じ)
    unauth_tables = extract_tables_with_links(unauth_html)
    for table in unauth_tables:
        records.extend(
            parse_unauthorized_table(
                table=table,
                source_url=unauthorized_url,
                as_of=as_of,
            )
        )

    if not dry_run:
        await repo.replace_all(records)

    return FacilityCrawlOutcome(
        rows_written=len(records),
        skipped_empty_rows=_count_empty_rows(auth_tables) + _count_empty_rows(unauth_tables),
        authorized_hash=auth_hash,
        unauthorized_hash=unauth_hash,
    )


async def run_half_yearly_facility(
    *,
    authorized_url: str,
    unauthorized_url: str,
    fetcher_config: PoliteFetcherConfig,
    facilities_repo: _FacilitiesRepoLike,
    runs_repo: EtlRunsRepo,
    run_id: str,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> EtlRunResult:
    """Cloud Run Job のエントリポイント。"""

    async def _job() -> EtlRunResult:
        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_replace_facilities(
                authorized_url=authorized_url,
                unauthorized_url=unauthorized_url,
                fetcher=fetcher,
                repo=facilities_repo,
                now=now,
                dry_run=dry_run,
            )
        return EtlRunResult(
            rows_written=outcome.rows_written,
            source_url=authorized_url,
            source_hash=_combine_hashes(outcome.authorized_hash, outcome.unauthorized_hash),
            status="success",
        )

    return await run_etl_job(
        job_name="half_yearly_facility_etl",
        run_id=run_id,
        repo=runs_repo,
        fn=_job,
        now=now,
    )


async def _fetch_text(fetcher: PoliteFetcher, url: str) -> tuple[str, str | None]:
    result = await fetcher.fetch(url)
    if isinstance(result, NotModified):
        # 半年次 Job では If-Modified-Since を立てない想定なので 304 は来ない前提。
        # 来た場合は空文字 + None を返し、parse は 0 件で続行する。
        return "", None
    assert isinstance(result, FetchResult)
    text = result.text
    return text, _sha256(text.encode("utf-8"))


def _combine_hashes(auth_hash: str | None, unauth_hash: str | None) -> str | None:
    """2 つの URL ハッシュを 1 つに合成 (どちらかでも変われば run する)。"""
    if auth_hash is None and unauth_hash is None:
        return None
    combined = f"{auth_hash or ''}/{unauth_hash or ''}"
    return _sha256(combined.encode("utf-8"))


def _count_empty_rows(tables: list[HtmlTable]) -> int:
    """全 cell が空白の行をカウント (parse 段階で skip された行)。"""
    n = 0
    for table in tables:
        for row in table.rows:
            if not any(cell.strip() for cell in row):
                n += 1
    return n


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "FacilityCrawlOutcome",
    "crawl_and_replace_facilities",
    "run_half_yearly_facility",
]
