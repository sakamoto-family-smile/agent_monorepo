"""純資産サマリ集計 (F3)。

- 現在の総資産・総負債・純資産を計算
- 月次ベースで純資産推移(スナップショットの`as_of`を月末に丸め、月ごと最新値を採用)

Phase 1 の簡易版: 取引ベースの CF 推移ではなく、Asset/Liability スナップショット優先。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from models.db import Asset, Liability
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class NetWorthSnapshot:
    as_of: date
    total_assets: Decimal
    total_liabilities: Decimal

    @property
    def net_worth(self) -> Decimal:
        return self.total_assets - self.total_liabilities


@dataclass(frozen=True)
class NetWorthSummary:
    household_id: str
    current: NetWorthSnapshot
    by_kind_assets: dict[str, Decimal]
    by_kind_liabilities: dict[str, Decimal]


async def compute_networth(
    session: AsyncSession, household_id: str, *, as_of: date | None = None
) -> NetWorthSummary:
    """現時点の純資産 (as_of 以前で最新のスナップショットの合算)。

    as_of 指定時はその日付以前のデータのみを対象。
    """
    # 資産合計 (全件合算。同一資産の更新はユーザーが上書き運用する前提)
    asset_q = select(Asset.kind, func.coalesce(func.sum(Asset.value), 0)).where(
        Asset.household_id == household_id
    )
    if as_of is not None:
        asset_q = asset_q.where(Asset.as_of <= as_of)
    asset_q = asset_q.group_by(Asset.kind)
    asset_rows = await session.execute(asset_q)
    by_kind_assets = {row[0]: Decimal(row[1] or 0) for row in asset_rows}
    total_assets = sum(by_kind_assets.values(), Decimal(0))

    liab_q = select(Liability.kind, func.coalesce(func.sum(Liability.balance), 0)).where(
        Liability.household_id == household_id
    )
    if as_of is not None:
        liab_q = liab_q.where(Liability.as_of <= as_of)
    liab_q = liab_q.group_by(Liability.kind)
    liab_rows = await session.execute(liab_q)
    by_kind_liabilities = {row[0]: Decimal(row[1] or 0) for row in liab_rows}
    total_liabilities = sum(by_kind_liabilities.values(), Decimal(0))

    snapshot = NetWorthSnapshot(
        as_of=as_of or date.today(),
        total_assets=total_assets,
        total_liabilities=total_liabilities,
    )
    return NetWorthSummary(
        household_id=household_id,
        current=snapshot,
        by_kind_assets=by_kind_assets,
        by_kind_liabilities=by_kind_liabilities,
    )
