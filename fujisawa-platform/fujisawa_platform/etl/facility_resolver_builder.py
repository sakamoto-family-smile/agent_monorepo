"""`FacilityResolver` を `FacilitiesRepo` から構築する helper。

ETL Job (admission / vacancy 等) は `施設名 → facility_id` の解決に
`FacilityResolver` を使うが、その入力 (`ResolverEntry` のリスト) は
`facilities` テーブルから読み出す必要がある。

本モジュールは `FacilitiesRepo.list_all()` の結果を `ResolverEntry` に
変換して `FacilityResolver` を組み立てる薄いラッパー。
"""

from __future__ import annotations

from typing import Protocol

from fujisawa_platform.etl._repos.facilities import FacilityRecord
from fujisawa_platform.resolver import FacilityResolver, ResolverEntry


class _FacilitiesRepoLike(Protocol):
    async def list_all(self) -> list[FacilityRecord]: ...


async def build_facility_resolver(
    repo: _FacilitiesRepoLike,
    *,
    threshold: float = 0.85,
) -> FacilityResolver:
    """`FacilitiesRepo` から `FacilityResolver` を組み立てる。

    Args:
        repo: `FacilitiesRepo` (DI 可能)。
        threshold: fuzzy match の閾値 (default 0.85)。

    Returns:
        ロード済み `FacilityResolver`。
    """
    records = await repo.list_all()
    entries = [
        ResolverEntry(
            facility_id=r.facility_id,
            canonical_name=r.name,
            aliases=r.aliases,
        )
        for r in records
    ]
    return FacilityResolver(entries, threshold=threshold)


__all__ = ["build_facility_resolver"]
