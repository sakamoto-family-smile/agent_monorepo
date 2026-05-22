"""edinet-client の公開型定義 (Pydantic v2 ベース)。

proposal 0006 §4.2 のデータモデルを実装。
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentType(StrEnum):
    """EDINET 書類タイプコード (`docTypeCode`)。

    EDINET 仕様の主要コードを抜粋。 取得は全件 (本 client 側で絞らない) が default、
    consumer 側で `DocumentType` でフィルタする想定。

    参考: <https://disclosure2.edinet-fsa.go.jp/weee0030.aspx>
    """

    ANNUAL_REPORT = "120"          # 有価証券報告書
    QUARTERLY_REPORT = "140"       # 四半期報告書
    SEMI_ANNUAL_REPORT = "160"     # 半期報告書
    EXTRAORDINARY_REPORT = "180"   # 臨時報告書
    AMENDMENT_REPORT = "130"       # 訂正届出書 (有報訂正等)
    MAJOR_HOLDING = "350"          # 大量保有報告書
    MAJOR_HOLDING_CHANGE = "360"   # 変更報告書 (大量保有関連)
    TENDER_OFFER = "490"           # 公開買付届出書
    INTERNAL_CONTROL = "200"       # 内部統制報告書
    SHARE_BUYBACK = "270"          # 自己株券買付状況報告書


class WithdrawalStatus(StrEnum):
    """`withdrawalStatus` の意味付け。"""

    ACTIVE = "0"      # 有効 (取下げられていない)
    WITHDRAWN = "1"   # 取下げられた書類


class DisclosureStatus(StrEnum):
    """`disclosureStatus` の意味付け。"""

    DISCLOSED = "0"        # 通常公開中
    STOPPED = "1"          # 開示停止 (e.g., 個人情報誤掲載)
    CANCELLED = "2"        # 公開停止


class DocumentMetadata(BaseModel):
    """EDINET の文書 1 件分のメタデータ (api/v2/documents.json の 1 要素を正規化)。

    proposal 0006 §4.2 に準拠。 `document_id` を PK として upsert される
    (status 系フィールドは提出後に変わる可能性があるため)。
    """

    model_config = ConfigDict(frozen=True)

    document_id: str = Field(min_length=1)        # docID (例: "S100ABC1")
    edinet_code: str                              # 提出者 EDINET code (例: "E02144")
    securities_code: str | None = None            # 4 桁証券コード (例: "7203")、 上場企業以外は None
    submitter_name: str                           # 提出者名
    document_type: DocumentType | str             # DocumentType に該当しない値は str で残す
    submit_date: date                             # 提出日
    period_end: date | None = None                # 期末日 (該当する書類のみ)
    description: str = ""                         # 書類概要 / 件名
    # ── status 系 (rolling 7 日窓 upsert で最新化される) ──
    withdrawal_status: int = 0                    # 0=有効, 1=取下げ
    disclosure_status: int = 0                    # 0=開示中, 1=開示停止, 2=公開停止
    doc_info_edit_status: int = 0                 # 0=未編集, 1=編集済
    xbrl_flag: bool = False
    pdf_flag: bool = False
    attach_doc_flag: bool = False

    @property
    def is_available(self) -> bool:
        """consumer (orchestrator) が採用すべき有効な書類か?"""
        return self.withdrawal_status == 0 and self.disclosure_status == 0


class DocumentBody(BaseModel):
    """`download()` の戻り値。 cache 経由でも同じ shape。"""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    document_id: str
    content_type: Literal["pdf", "xbrl_zip", "attach_zip"]
    bytes_payload: bytes = Field(repr=False)       # 大容量なので repr では表示しない
    fetched_at: datetime
    from_cache: bool                               # cache hit から取得されたか


__all__ = [
    "DisclosureStatus",
    "DocumentBody",
    "DocumentMetadata",
    "DocumentType",
    "WithdrawalStatus",
]
