"""HtmlTable → FacilityRecord 変換 (認可・認可外で別関数)。

調査ノート §A4 から:
- 認可: 5 テーブル合計 128 件 (公立 13 + 法人等 88 + 認定こども園 6 + 小規模 19 + 家庭的 2)
  - 列構成: 施設名 / 所在地番 / 電話番号 (法人等以降に外部リンク列が付く)
- 認可外: 4 テーブル合計 32 件 (駅エリア別)
  - 列構成: 施設名(類型) / 所在地 / 電話番号 / 定員
  - 「駅北口・徒歩 7 分」表記が混在 → 正規表現でパース
  - 類型は施設名後の括弧内 (藤沢型 A 型 / B 型 / 企業主導型 / etc.)
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from fujisawa_platform.etl._html_table import HtmlTable
from fujisawa_platform.etl._repos.facilities import FacilityRecord
from fujisawa_platform.etl.facility_aliases import R4_FACILITY_ALIASES

# 認可の facility_type に対応する slug prefix。
# slugify_facility_id() で facility_id 衝突を防ぎつつ可読性も維持する。
_TYPE_SLUGS: dict[str, str] = {
    "公立保育所": "kouritsu",
    "法人等保育所": "houjin",
    "認定こども園": "kodomoen",
    "小規模保育事業": "kogata",
    "家庭的保育事業": "kateiteki",
    "認可外保育施設": "ninkagai",
}

_FALLBACK_UNAUTHORIZED_TYPE = "認可外保育施設"

_TYPE_IN_NAME = re.compile(r"^(?P<name>.+?)[\(（](?P<type>[^)）]+)[\)）]\s*$")
_WALK_MINUTES = re.compile(r"(?P<station>[^\s、,]+?駅).*?徒歩\s*(?P<min>\d+)\s*分")


def slugify_facility_id(facility_type: str, name: str) -> str:
    """`facility_type` の slug + 名前の SHA-256 先頭 12 桁。

    例: ("公立保育所", "藤沢保育園") → "kouritsu-3a4b5c6d7e8f"
    同じ施設には常に同じ ID が返るので、半年次の replace_all 後も
    `vacancy_snapshots.facility_id REFERENCES facilities` が安定して効く。
    """
    prefix = _TYPE_SLUGS.get(facility_type, "facility")
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def parse_walk_minutes(text: str) -> tuple[str | None, int | None]:
    """「藤沢駅北口徒歩 7 分」のような表記から (駅名, 徒歩分数) を抽出。

    抽出できない場合は (None, None)。
    """
    match = _WALK_MINUTES.search(text)
    if match is None:
        return None, None
    return match.group("station"), int(match.group("min"))


def parse_authorized_table(
    *,
    table: HtmlTable,
    facility_type: str,
    source_url: str,
    as_of: datetime,
) -> list[FacilityRecord]:
    """認可保育施設の 1 テーブルを `FacilityRecord` のリストに変換。

    必須列 (左から 3 列):
        - 施設名 / 所在地番 / 電話番号
    任意列:
        - 4 列目以降に外部リンク (列インデックス >= 3 の `row_links` を採用)
    """
    records: list[FacilityRecord] = []
    for row, links in zip(table.rows, table.row_links, strict=False):
        if len(row) < 3:
            continue
        name = row[0].strip()
        address = row[1].strip()
        phone = row[2].strip() or None
        if not name or not address:
            continue

        official_url = next(
            (url for col_idx, url in links.items() if col_idx >= 3),
            None,
        )

        records.append(
            FacilityRecord(
                facility_id=slugify_facility_id(facility_type, name),
                name=name,
                facility_type=facility_type,
                address=address,
                phone=phone,
                official_url=official_url,
                aliases=R4_FACILITY_ALIASES.get(name, []),
                source_url=source_url,
                as_of=as_of,
            )
        )
    return records


def parse_unauthorized_table(
    *,
    table: HtmlTable,
    source_url: str,
    as_of: datetime,
) -> list[FacilityRecord]:
    """認可外保育施設の 1 テーブルを `FacilityRecord` のリストに変換。

    必須列 (左から 4 列):
        - 施設名(類型) / 所在地 / 電話番号 / 定員
    """
    records: list[FacilityRecord] = []
    for row in table.rows:
        if len(row) < 4:
            continue
        raw_name = row[0].strip()
        address = row[1].strip()
        phone = row[2].strip() or None
        capacity = _parse_int(row[3])
        if not raw_name or not address:
            continue

        name, facility_type = _split_name_and_type(raw_name)
        station, minutes = parse_walk_minutes(address)

        records.append(
            FacilityRecord(
                facility_id=slugify_facility_id(facility_type, name),
                name=name,
                facility_type=facility_type,
                address=address,
                phone=phone,
                capacity=capacity,
                nearest_station=station,
                walk_minutes=minutes,
                aliases=R4_FACILITY_ALIASES.get(name, []),
                source_url=source_url,
                as_of=as_of,
            )
        )
    return records


def _split_name_and_type(raw_name: str) -> tuple[str, str]:
    """「A 保育園 (藤沢型 A 型)」を ("A 保育園", "藤沢型 A 型") に分ける。

    括弧が無ければ (raw_name, 認可外保育施設) にフォールバック。
    """
    match = _TYPE_IN_NAME.match(raw_name)
    if match is None:
        return raw_name, _FALLBACK_UNAUTHORIZED_TYPE
    return match.group("name").strip(), match.group("type").strip()


def _parse_int(value: str) -> int | None:
    cleaned = value.strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


__all__ = [
    "parse_authorized_table",
    "parse_unauthorized_table",
    "parse_walk_minutes",
    "slugify_facility_id",
]
