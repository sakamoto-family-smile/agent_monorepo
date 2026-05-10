"""FreshnessMetadata の自動付与 helpers。

ETL Job は取得時に `as_of` (現在時刻) と `source_url` を必ず設定し、
PDF の場合は `snapshot_date` と `source_pdf_url` を併記する。
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from fujisawa_platform.models import FreshnessMetadata

# PDF ファイル名からの日付抽出パターン:
#   akizyoukyou20240401-1a.pdf → 2024-04-01
#   20260115092454.pdf         → 2026-01-15
_DATE_PATTERN = re.compile(r"(?P<y>20\d{2})(?P<m>0[1-9]|1[0-2])(?P<d>0[1-9]|[12]\d|3[01])")


def build_freshness(
    *,
    source_url: str,
    source_pdf_url: str | None = None,
    snapshot_date: date | None = None,
    etl_job_id: str | None = None,
    schema_version: str = "v1",
    as_of: datetime | None = None,
) -> FreshnessMetadata:
    """FreshnessMetadata を構築する helper。

    Args:
        source_url: 元ページの URL (必須)。
        source_pdf_url: PDF 由来の場合の元 PDF URL。
        snapshot_date: PDF 発行日。指定がなければ source_pdf_url から推定を試みる。
        etl_job_id: ETL ジョブ ID。
        schema_version: 出力 schema バージョン。
        as_of: 取得日時。省略時は現在時刻 (UTC)。

    Returns:
        正規化された FreshnessMetadata。
    """
    if as_of is None:
        as_of = datetime.now(UTC)
    if snapshot_date is None and source_pdf_url is not None:
        snapshot_date = parse_pdf_date_from_filename(source_pdf_url)

    return FreshnessMetadata(
        as_of=as_of,
        source_url=source_url,  # type: ignore[arg-type]
        source_pdf_url=source_pdf_url,  # type: ignore[arg-type]
        snapshot_date=snapshot_date,
        etl_job_id=etl_job_id,
        schema_version=schema_version,
    )


def parse_pdf_date_from_filename(url_or_filename: str) -> date | None:
    """PDF ファイル名 / URL から日付を推定する。

    藤沢市の PDF は ファイル名に YYYYMMDD を含むケースが多い (調査 §A2):
      - `akizyoukyou20240401-1a.pdf` → 2024-04-01
      - `mousikomizyoukyou20230401.pdf` → 2023-04-01
      - `20260115092454.pdf` → 2026-01-15

    抽出できない場合は None。

    Args:
        url_or_filename: PDF の URL または ファイル名のみ。

    Returns:
        抽出した日付。パターン不一致なら None。
    """
    # URL の場合は最後の path component を取る
    filename = url_or_filename.rsplit("/", 1)[-1]
    match = _DATE_PATTERN.search(filename)
    if not match:
        return None
    try:
        return date(int(match["y"]), int(match["m"]), int(match["d"]))
    except ValueError:
        return None
