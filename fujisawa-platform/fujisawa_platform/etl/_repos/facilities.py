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
        """incoming list で `facilities` テーブルを更新する (UPSERT + 条件付き DELETE)。

        旧実装は `DELETE FROM facilities` + 一括 INSERT だったが、 admission_results
        等の下流テーブルが FK 参照を持つようになると DELETE が
        ForeignKeyViolationError で fail する。 facility_id は
        `slugify_facility_id(type, name)` で stable なので、 incoming と既存で同じ
        ID なら UPDATE、 新規なら INSERT、 incoming に無く下流参照も無い既存は
        DELETE、 という UPSERT + 条件付き DELETE で再設計する。

        単一トランザクションで実行することで部分更新を防ぐ点は変わらない。

        Returns:
            UPSERT した件数 (= len(records))。 削除件数は含まない。
        """
        incoming_ids = [r.facility_id for r in records]
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # まず incoming を UPSERT (facility_id が一致すれば UPDATE)
                for record in records:
                    await conn.execute(
                        """
                        INSERT INTO facilities (
                            facility_id, name, facility_type, address, phone,
                            capacity, nearest_station, walk_minutes, official_url,
                            aliases, lat, lng, source_url, as_of, schema_version
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                                  $10::jsonb, $11, $12, $13, $14, $15)
                        ON CONFLICT (facility_id) DO UPDATE SET
                            name = EXCLUDED.name,
                            facility_type = EXCLUDED.facility_type,
                            address = EXCLUDED.address,
                            phone = EXCLUDED.phone,
                            capacity = EXCLUDED.capacity,
                            nearest_station = EXCLUDED.nearest_station,
                            walk_minutes = EXCLUDED.walk_minutes,
                            official_url = EXCLUDED.official_url,
                            aliases = EXCLUDED.aliases,
                            lat = EXCLUDED.lat,
                            lng = EXCLUDED.lng,
                            source_url = EXCLUDED.source_url,
                            as_of = EXCLUDED.as_of,
                            schema_version = EXCLUDED.schema_version
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

                # incoming に無く、 下流 FK 参照も持たない facility のみ DELETE。
                # FK 参照がある「閉園扱い」 facility は残し、 過去 admission_results
                # 等の整合性を保つ。
                await conn.execute(
                    """
                    DELETE FROM facilities f
                    WHERE f.facility_id != ALL($1::text[])
                      AND NOT EXISTS (
                          SELECT 1 FROM admission_results ar
                          WHERE ar.facility_id = f.facility_id
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM vacancy_snapshots vs
                          WHERE vs.facility_id = f.facility_id
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM application_snapshots aps
                          WHERE aps.facility_id = f.facility_id
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM competition_stats cs
                          WHERE cs.facility_id = f.facility_id
                      )
                    """,
                    incoming_ids,
                )
        return len(records)

    async def count(self) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM facilities")
        if row is None:
            return 0
        return int(row["c"])

    async def list_all(self) -> list[FacilityRecord]:
        """全件を取得 (~160 件想定なのでページングなし)。

        - ETL Job (admission / vacancy) が `FacilityResolver` を組み立てる入力として利用
        - consumer 側からも将来呼び出される可能性あり (Phase 5+)
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    facility_id, name, facility_type, address, phone,
                    capacity, nearest_station, walk_minutes, official_url,
                    aliases, lat, lng, source_url, as_of, schema_version
                FROM facilities
                ORDER BY facility_id
                """
            )
        return [_row_to_record(r) for r in rows]


def _row_to_record(row: Any) -> FacilityRecord:
    aliases = row["aliases"]
    if isinstance(aliases, str):
        aliases = json.loads(aliases) if aliases else []
    elif aliases is None:
        aliases = []
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
