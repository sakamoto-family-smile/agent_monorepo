"""共通の値オブジェクト。

`FreshnessMetadata` は本基盤が扱う全データ (HTML page / PDF chunk / facility /
vacancy_snapshot 等) に必ず付与される鮮度メタデータ。consumer 側はこれを応答に
強制的に表示する (proposal 0004 §3.3 / 0005 §4.3 の出典強制ルール)。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class FreshnessMetadata(BaseModel):
    """データの鮮度・出典情報。

    consumer agent (info-bot / 保活) は `as_of` の経過日数を計算し、
    「N 日前のデータ」を応答に表示する。
    `source_url` は引用要件を満たすため必須。`source_pdf_url` / `snapshot_date`
    は PDF 由来データのみ。
    """

    model_config = ConfigDict(frozen=True)

    as_of: datetime = Field(
        description="ETL がこのデータを取得・確定した時刻 (UTC)。",
    )
    source_url: HttpUrl = Field(
        description="元ページの URL。consumer は応答に必ず引用する。",
    )
    source_pdf_url: HttpUrl | None = Field(
        default=None,
        description="PDF 由来データの場合の元 PDF URL。",
    )
    snapshot_date: date | None = Field(
        default=None,
        description="PDF 発行日 (PDF が掲載された日付)。月次空き状況等で使う。",
    )
    etl_job_id: str | None = Field(
        default=None,
        description="どの ETL ジョブが書き込んだか。トレースに使う。",
    )
    schema_version: str = Field(
        default="v1",
        description="出力 schema のバージョン。Docling 等の更新で構造が変わったらインクリメント。",
    )

    def days_since(self, *, now: datetime | None = None) -> int:
        """`as_of` からの経過日数。consumer の鮮度注記に使う。

        Args:
            now: テスト用の固定時刻。本番呼び出しでは省略 (UTC 現在時刻)。

        Returns:
            経過日数 (0 以上の整数、未来日付の場合も 0)。
        """
        current = now if now is not None else datetime.now(UTC)
        delta = current - self.as_of
        return max(0, delta.days)
