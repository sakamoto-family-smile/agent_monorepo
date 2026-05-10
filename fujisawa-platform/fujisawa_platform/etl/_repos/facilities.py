"""FacilitiesRepo: `facilities` テーブルへの薄い CRUD (proposal 0003 §4.3 / §4.5.5)。

`facilities` は半年に 1 回しか更新しない 160 件規模のマスタなので、
**全削除 → 全 INSERT を 1 トランザクション** で行う (proposal 0003 §4.5.5)。
consumer 側は SELECT 失敗時に tenacity retry で吸収する想定。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # pragma: no cover
    import asyncpg


class FacilityRecord(BaseModel):
    """`facilities` テーブル 1 行のモデル。"""

    model_config = ConfigDict(frozen=True)

    facility_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    facility_type: str = Field(min_length=1)  # 公立保育所 / 法人等保育所 / 認定こども園 / etc.
    address: str = Field(min_length=1)
    phone: str | None = None
    capacity: int | None = None
    nearest_station: str | None = None
    walk_minutes: int | None = None
    official_url: str | None = None
    aliases: list[str] = Field(default_factory=list)  # 表記ゆれ吸収用
    lat: float | None = None
    lng: float | None = None
    source_url: str
    as_of: datetime
    schema_version: str = "v1"


class FacilitiesRepo:
    """`facilities` テーブルへのアクセス Repository。"""

    def __init__(self, *, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def replace_all(self, records: list[FacilityRecord]) -> int:
        """全件を新しいリストで置き換える (DELETE + INSERT を 1 トランザクション)。

        Returns:
            INSERT した件数。空 list を渡した場合は 0 (DELETE のみ実行される)。
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM facilities")
                for record in records:
                    await conn.execute(
                        """
                        INSERT INTO facilities (
                            facility_id, name, facility_type, address, phone,
                            capacity, nearest_station, walk_minutes, official_url,
                            aliases, lat, lng, source_url, as_of, schema_version
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                                  $10::jsonb, $11, $12, $13, $14, $15)
                        """,
                        record.facility_id,
                        record.name,
                        record.facility_type,
                        record.address,
                        record.phone,
                        record.capacity,
                        record.nearest_station,
                        record.walk_minutes,
                        record.official_url,
                        json.dumps(record.aliases, ensure_ascii=False),
                        record.lat,
                        record.lng,
                        record.source_url,
                        record.as_of,
                        record.schema_version,
                    )
        return len(records)

    async def count(self) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM facilities")
        if row is None:
            return 0
        return int(row["c"])


def _row_to_record(row: Any) -> FacilityRecord:  # pragma: no cover — 将来の SELECT 用
    aliases = row["aliases"]
    if isinstance(aliases, str):
        aliases = json.loads(aliases)
    return FacilityRecord(
        facility_id=row["facility_id"],
        name=row["name"],
        facility_type=row["facility_type"],
        address=row["address"],
        phone=row["phone"],
        capacity=row["capacity"],
        nearest_station=row["nearest_station"],
        walk_minutes=row["walk_minutes"],
        official_url=row["official_url"],
        aliases=list(aliases or []),
        lat=row["lat"],
        lng=row["lng"],
        source_url=row["source_url"],
        as_of=row["as_of"],
        schema_version=row.get("schema_version", "v1"),
    )


__all__ = ["FacilitiesRepo", "FacilityRecord"]
