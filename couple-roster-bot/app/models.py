"""ドメインモデル — 名簿レコードと「間柄」の定義。

immutability を守るため `RosterEntry` は `frozen=True`。更新は `with_updates`
で新しいインスタンスを返す（既存インスタンスは変更しない）。

`Relation` はスプレッドシートの列・LIFF フォームのプルダウン・CSV 検証の
唯一の真実。候補を増やすときはこの enum だけを変更すればよい。
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

ZIP_PATTERN = re.compile(r"^\d{3}-?\d{4}$")


class Relation(StrEnum):
    """家族の間柄（選択式）。値がそのままスプレッドシートに保存される。"""

    FATHER = "父"
    MOTHER = "母"
    SIBLING = "兄弟姉妹"
    GRANDPARENT = "祖父母"
    CHILD = "子"
    RELATIVE = "親戚"
    FRIEND = "友人・知人"
    WORK = "仕事関係"
    OTHER = "その他"

    @classmethod
    def choices(cls) -> list[str]:
        """LIFF プルダウン / CSV 検証で使う表示順の候補一覧。"""
        return [r.value for r in cls]

    @classmethod
    def from_label(cls, label: str) -> Relation | None:
        """表示ラベル（日本語）から enum を引く。未知の値は None。"""
        normalized = (label or "").strip()
        for r in cls:
            if r.value == normalized:
                return r
        return None


# スプレッドシートのヘッダ行と列順。CSV / Sheets 両方で共有する。
FIELD_ORDER: tuple[str, ...] = (
    "id",
    "name",
    "kana",
    "zip",
    "address",
    "relation",
    "note",
    "created_by",
    "created_at",
    "updated_at",
)


class RosterEntry(BaseModel):
    """名簿の 1 レコード（スプレッドシートの 1 行に対応）。イミュータブル。"""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    address: str
    relation: Relation
    kana: str = ""
    zip: str = ""
    note: str = ""
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""

    def with_updates(self, **changes: object) -> RosterEntry:
        """指定フィールドだけ差し替えた新しいインスタンスを返す（元は不変）。"""
        return self.model_copy(update=changes)

    def to_row(self) -> list[str]:
        """スプレッドシート 1 行分の文字列配列（`FIELD_ORDER` 順）。"""
        values = {
            "id": self.id,
            "name": self.name,
            "kana": self.kana,
            "zip": self.zip,
            "address": self.address,
            "relation": self.relation.value,
            "note": self.note,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return [values[field] for field in FIELD_ORDER]

    @classmethod
    def from_row(cls, row: dict[str, str]) -> RosterEntry:
        """スプレッドシートの行（ヘッダ→値の dict）から復元する。"""
        relation = Relation.from_label(row.get("relation", "")) or Relation.OTHER
        return cls(
            id=row.get("id", ""),
            name=row.get("name", ""),
            kana=row.get("kana", ""),
            zip=row.get("zip", ""),
            address=row.get("address", ""),
            relation=relation,
            note=row.get("note", ""),
            created_by=row.get("created_by", ""),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
        )


class EntryValidationError(ValueError):
    """名簿レコードの検証エラー（必須欠落・間柄候補外・郵便番号形式）。"""


def dedup_key(name: str, address: str) -> str:
    """重複判定キー。氏名＋住所の空白差を無視して比較する。"""
    return f"{_squash(name)}|{_squash(address)}"


def _squash(value: str) -> str:
    """前後空白・全角/半角スペースを畳んで比較用に正規化する。"""
    return re.sub(r"\s+", "", (value or "").strip())


class EntryDraft(BaseModel):
    """未検証の入力（LIFF フォーム / CSV 行 / OCR 抽出）を表す下書き。"""

    name: str = ""
    kana: str = ""
    zip: str = ""
    address: str = ""
    relation: str = ""
    note: str = ""

    def normalized(self) -> EntryDraft:
        """各項目の前後空白を除去した新しい下書きを返す。"""
        return EntryDraft(
            name=self.name.strip(),
            kana=self.kana.strip(),
            zip=self.zip.strip(),
            address=self.address.strip(),
            relation=self.relation.strip(),
            note=self.note.strip(),
        )

    def validate_draft(self) -> Relation:
        """必須・形式を検証し、正規化済みの `Relation` を返す。失敗時は例外。"""
        draft = self.normalized()
        if not draft.name:
            raise EntryValidationError("名前は必須です")
        if not draft.address:
            raise EntryValidationError("住所は必須です")
        relation = Relation.from_label(draft.relation)
        if relation is None:
            raise EntryValidationError(
                f"間柄が不正です: '{draft.relation}'（候補: {', '.join(Relation.choices())}）"
            )
        if draft.zip and not ZIP_PATTERN.match(draft.zip):
            raise EntryValidationError(f"郵便番号の形式が不正です: '{draft.zip}'")
        return relation


DraftLike = EntryDraft

__all__ = [
    "EntryDraft",
    "EntryValidationError",
    "FIELD_ORDER",
    "Relation",
    "RosterEntry",
    "ZIP_PATTERN",
    "dedup_key",
]
