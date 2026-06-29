"""合成-but-grounded 請求書生成器。

既知の構造化レコード (gold) から日本語請求書テキストを生成し、各フィールドの
**正解値が原文のどこにあるか (char span)** を同時に記録する。これにより:
  - 正解ラベルが自動で揃う (精度検証に必須)
  - 接地検証の正否を「真の span」と突合して評価できる
  - ラベル位置を記録するので帰属チェック(C2)の評価ができる

seed 固定で完全再現可能。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..schema import FieldType, Invoice, LineItem, field_type_of

_ISSUERS = [
    ("株式会社XYZ製作所", "東京都千代田区丸の内1-2-3"),
    ("ABCソリューションズ株式会社", "大阪府大阪市北区梅田4-5-6"),
    ("有限会社サンライズ工業", "愛知県名古屋市中区栄7-8-9"),
    ("グローバルテック株式会社", "福岡県福岡市博多区博多駅前1-1-1"),
]
_RECIPIENTS = [
    "株式会社みらい商事",
    "東日本物流株式会社",
    "株式会社ひかりデザイン",
    "中央メディカル株式会社",
]
_ITEMS = [
    "オフィスデスク", "メッシュチェア", "書類キャビネット", "LEDデスクライト",
    "ホワイトボード", "シュレッダー", "会議用テーブル", "USBハブ",
]


@dataclass(frozen=True)
class LabelOccurrence:
    """原文中のラベル出現 (帰属チェック評価用)。"""

    label: str
    start: int
    owners: frozenset[str]


@dataclass
class GoldSample:
    """生成された 1 サンプル。

    ドメイン非依存の評価/抽出のために、各フィールドの型を ``field_types`` に保持する
    (metrics・mock 抽出器はこれを参照し、ドメイン固有の解決関数に依存しない)。
    """

    sample_id: int
    text: str
    spans: dict[str, tuple[int, int]]  # field_id -> (start, end) 正解span
    field_types: dict[str, FieldType] = field(default_factory=dict)
    record: object | None = None  # ドメインの pydantic レコード (任意)
    labels: list[LabelOccurrence] = field(default_factory=list)

    def gold_value(self, field_id: str) -> str:
        """field_id に対応する原文表記の正解値 (text[start:end])。"""
        s, e = self.spans[field_id]
        return self.text[s:e]


class _Builder:
    """テキストを組み立てつつ field/label の char span を記録する。"""

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._pos = 0
        self.spans: dict[str, tuple[int, int]] = {}
        self.labels: list[LabelOccurrence] = []

    def add(self, s: str) -> None:
        self._parts.append(s)
        self._pos += len(s)

    def add_field(self, field_id: str, s: str) -> None:
        start = self._pos
        self.add(s)
        self.spans[field_id] = (start, self._pos)

    def add_label(self, label: str, owners: frozenset[str]) -> None:
        self.labels.append(LabelOccurrence(label, self._pos, owners))
        self.add(label)

    def text(self) -> str:
        return "".join(self._parts)


def _jp_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{int(y)}年{int(m)}月{int(d)}日"


def generate_sample(sample_id: int) -> GoldSample:
    """seed=sample_id で 1 サンプルを生成。"""
    rng = random.Random(sample_id)

    issuer_name, issuer_address = rng.choice(_ISSUERS)
    recipient_name = rng.choice(_RECIPIENTS)
    invoice_no = f"INV-{2024 + rng.randint(0, 2)}-{rng.randint(1, 99999):05d}"
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    issue_iso = f"{2024 + rng.randint(0, 2)}-{month:02d}-{day:02d}"
    due_iso = f"{int(issue_iso[:4])}-{(month % 12) + 1:02d}-{day:02d}"

    n_items = rng.randint(2, 4)
    items: list[LineItem] = []
    chosen = rng.sample(_ITEMS, n_items)
    for name in chosen:
        qty = rng.randint(1, 9)
        unit = rng.choice([800, 1200, 2400, 3600, 9400, 12800]) + rng.randint(0, 3) * 100
        items.append(LineItem(description=name, quantity=qty, unit_price=unit, amount=qty * unit))

    subtotal = sum(it.amount for it in items)
    tax = round(subtotal * 0.1)
    total = subtotal + tax

    record = Invoice(
        issuer_name=issuer_name,
        issuer_address=issuer_address,
        recipient_name=recipient_name,
        invoice_no=invoice_no,
        issue_date=issue_iso,
        due_date=due_iso,
        line_items=items,
        subtotal=subtotal,
        tax=tax,
        total=total,
    )

    b = _Builder()
    b.add("請求書\n\n")
    b.add_label("請求書番号", frozenset({"invoice_no"}))
    b.add(": ")
    b.add_field("invoice_no", invoice_no)
    b.add("\n")
    b.add_label("発行日", frozenset({"issue_date"}))
    b.add(": ")
    b.add_field("issue_date", _jp_date(issue_iso))
    b.add("\n")
    b.add_label("お支払期限", frozenset({"due_date"}))
    b.add(": ")
    b.add_field("due_date", _jp_date(due_iso))
    b.add("\n\n")

    b.add_label("請求先", frozenset({"recipient_name"}))
    b.add(":\n  ")
    b.add_field("recipient_name", recipient_name)
    b.add(" 御中\n\n")

    b.add_label("発行元", frozenset({"issuer_name", "issuer_address"}))
    b.add(":\n  ")
    b.add_field("issuer_name", issuer_name)
    b.add("\n  ")
    b.add_field("issuer_address", issuer_address)
    b.add("\n\n明細:\n")
    for i, it in enumerate(items):
        b.add("  ")
        b.add_field(f"line_items[{i}].description", it.description)
        b.add("  数量 ")
        b.add_field(f"line_items[{i}].quantity", str(it.quantity))
        b.add("  単価 ")
        b.add_field(f"line_items[{i}].unit_price", f"{it.unit_price:,}")
        b.add("  金額 ")
        b.add_field(f"line_items[{i}].amount", f"{it.amount:,}")
        b.add("\n")

    b.add("\n")
    b.add_label("小計", frozenset({"subtotal"}))
    b.add(": ")
    b.add_field("subtotal", f"{subtotal:,}")
    b.add("\n")
    b.add_label("消費税", frozenset({"tax"}))
    b.add(": ")
    b.add_field("tax", f"{tax:,}")
    b.add("\n")
    b.add_label("合計", frozenset({"total"}))
    b.add(": ")
    b.add_field("total", f"{total:,}")
    b.add("\n")

    return GoldSample(
        sample_id=sample_id,
        text=b.text(),
        spans=b.spans,
        field_types={fid: field_type_of(fid) for fid in b.spans},
        record=record,
        labels=b.labels,
    )


def generate_dataset(start: int, end: int) -> list[GoldSample]:
    """[start, end) の sample_id でデータセットを生成。"""
    return [generate_sample(i) for i in range(start, end)]
