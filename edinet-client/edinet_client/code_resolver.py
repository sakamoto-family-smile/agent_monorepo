"""ticker (証券コード) ⇔ EDINET コード の双方向マッピング。

EDINET 公式の `Edinetcode.csv` (約 50,000 行) を入力として読み、 in-memory dict
を構築する。 CSV は EDINET の「コード一覧」 ダウンロードページから取得する想定:
<https://disclosure2.edinet-fsa.go.jp/weee0030.aspx>

CSV 仕様 (header 2 行目):
    ＥＤＩＮＥＴコード, 提出者種別, 上場区分, 連結の有無, 資本金, 決算日,
    提出者名, 提出者名（英字）, 提出者名（ヨミ）, 所在地, 提出者業種,
    証券コード, 提出者法人番号

- 1 行目はダウンロード日時など metadata なので skip
- 証券コードは **5 桁 + 末尾 0** 表記 (例: トヨタは "72030")。 yfinance の
  "7203.T" / "7203" 形式の入力には末尾 0 を付加して照合する
- 上場企業以外 (ファンド / 海外法人等) は 証券コード = 空欄
- encoding: 公式は Shift-JIS だが新フォーマットは UTF-8 (BOM 付き) もあり、
  両方を試行する
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# CSV 列ヘッダ (全角)
_COL_EDINET_CODE = "ＥＤＩＮＥＴコード"
_COL_SUBMITTER = "提出者種別"
_COL_LISTING = "上場区分"
_COL_FILER_NAME = "提出者名"
_COL_FILER_NAME_EN = "提出者名（英字）"
_COL_FILER_NAME_KANA = "提出者名（ヨミ）"
_COL_INDUSTRY = "提出者業種"
_COL_SECURITIES = "証券コード"
_COL_CORPORATE_NUMBER = "提出者法人番号"

# ticker 入力の正規化: "7203" / "7203.T" / "7203.JP" / "72030" / "285A" / "285A.T" を 5 桁に揃える
_TICKER_SUFFIX_RE = re.compile(r"\.(T|JP|JPN)$", re.IGNORECASE)
# 4 文字 alphanumeric (例: 7203, 285A) or 5 文字 (例: 72030, 285A0) を受理
_TICKER_4CHAR_RE = re.compile(r"^[0-9A-Za-z]{4}$")
_TICKER_5CHAR_RE = re.compile(r"^[0-9A-Za-z]{5}$")


@dataclass(frozen=True)
class EdinetCodeRecord:
    """`Edinetcode.csv` の 1 行を正規化したもの。"""

    edinet_code: str
    securities_code: str | None       # 5 桁表記 (上場企業以外は None)
    submitter_name: str
    submitter_type: str               # 例: "内国法人・株式会社"
    listing: str                      # 例: "上場"
    submitter_name_en: str | None
    submitter_name_kana: str | None
    industry: str | None              # 業種
    corporate_number: str | None      # 法人番号

    @property
    def is_listed(self) -> bool:
        return self.listing.strip() == "上場"


class EdinetCodeResolver:
    """ticker (証券コード) ⇔ EDINET code の高速 lookup。

    Example:
        resolver = EdinetCodeResolver.from_csv_path("Edinetcode.csv")
        edinet_code = resolver.resolve_edinet_code("7203.T")  # → "E02144"
        record = resolver.get("7203")                          # → EdinetCodeRecord
    """

    def __init__(self, records: Iterable[EdinetCodeRecord]) -> None:
        self._records: list[EdinetCodeRecord] = list(records)
        # 双方向 index
        self._by_securities: dict[str, EdinetCodeRecord] = {}
        self._by_edinet: dict[str, EdinetCodeRecord] = {}
        for rec in self._records:
            if rec.securities_code:
                self._by_securities[rec.securities_code] = rec
            self._by_edinet[rec.edinet_code] = rec

    # ─── factory ───────────────────────────────────────────────

    @classmethod
    def from_csv_path(cls, path: str | Path) -> EdinetCodeResolver:
        path = Path(path)
        return cls.from_csv_bytes(path.read_bytes())

    @classmethod
    def from_csv_bytes(cls, csv_bytes: bytes) -> EdinetCodeResolver:
        """Edinetcode.csv (Shift-JIS / UTF-8) をパースして resolver を構築。"""
        text = _decode_csv(csv_bytes)
        records = list(_parse_csv_text(text))
        return cls(records)

    # ─── public API ────────────────────────────────────────────

    def resolve_edinet_code(self, ticker: str) -> str | None:
        """`7203.T` / `7203` / `72030` から EDINET code を返す。 未登録なら None。"""
        rec = self.get(ticker)
        return rec.edinet_code if rec else None

    def resolve_securities_code(self, edinet_code: str) -> str | None:
        """逆引き: edinet_code → securities_code (5 桁) を返す。 未登録 / 非上場なら None。"""
        rec = self._by_edinet.get(edinet_code.strip())
        return rec.securities_code if rec else None

    def get(self, ticker: str) -> EdinetCodeRecord | None:
        """フル record で返す (ticker から securities_code に正規化して lookup)。"""
        normalized = _normalize_ticker_to_securities_code(ticker)
        if not normalized:
            return None
        return self._by_securities.get(normalized)

    def get_by_edinet_code(self, edinet_code: str) -> EdinetCodeRecord | None:
        return self._by_edinet.get(edinet_code.strip())

    def __len__(self) -> int:
        return len(self._records)


# ─────────────────────────────────────────────────────────────────
# private helpers
# ─────────────────────────────────────────────────────────────────


def _normalize_ticker_to_securities_code(ticker: str) -> str | None:
    """ticker を EDINET の証券コード表記 (5 文字、 末尾 0) に正規化。

    対応する入力形式:
    - `"7203.T"` / `"7203"` (4 桁数字) → `"72030"`
    - `"72030"` (5 桁数字) → `"72030"` (そのまま)
    - `"285A.T"` / `"285A"` (4 文字 alphanumeric、 末尾が英字) → `"285A0"`
        ※ 2024 年以降の新表記 (キオクシア等)
    - `"285A0"` (5 文字 alphanumeric) → `"285A0"`

    未対応 / 不正な入力は None。
    """
    if not ticker:
        return None
    s = ticker.strip().upper()  # 大文字に揃える (EDINET 表記準拠)
    s = _TICKER_SUFFIX_RE.sub("", s)
    if _TICKER_4CHAR_RE.match(s):
        return s + "0"
    if _TICKER_5CHAR_RE.match(s):
        return s
    return None


def _decode_csv(payload: bytes) -> str:
    """Shift-JIS / UTF-8 (BOM 有り無し) を試行して decode。"""
    for encoding in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("could not decode Edinetcode.csv (tried utf-8 / shift_jis)")


def _parse_csv_text(text: str) -> Iterable[EdinetCodeRecord]:
    """CSV テキストを iterable[EdinetCodeRecord] に変換。

    EDINET CSV の構造:
    - 1 行目: ダウンロード日時のメタデータ (skip)
    - 2 行目: 列ヘッダ
    - 3 行目〜: 各社のレコード
    """
    lines = text.splitlines()
    if not lines:
        return
    # 1 行目を skip、 2 行目以降を csv.DictReader に渡す
    body = "\n".join(lines[1:])
    reader = csv.DictReader(io.StringIO(body))
    for raw in reader:
        # 列名は全角。 trim とともに取り出す
        edinet_code = (raw.get(_COL_EDINET_CODE) or "").strip()
        if not edinet_code:
            continue  # 空行 / メタ行はスキップ
        securities_raw = (raw.get(_COL_SECURITIES) or "").strip()
        securities_code = securities_raw if securities_raw else None
        yield EdinetCodeRecord(
            edinet_code=edinet_code,
            securities_code=securities_code,
            submitter_name=(raw.get(_COL_FILER_NAME) or "").strip(),
            submitter_type=(raw.get(_COL_SUBMITTER) or "").strip(),
            listing=(raw.get(_COL_LISTING) or "").strip(),
            submitter_name_en=(raw.get(_COL_FILER_NAME_EN) or "").strip() or None,
            submitter_name_kana=(raw.get(_COL_FILER_NAME_KANA) or "").strip() or None,
            industry=(raw.get(_COL_INDUSTRY) or "").strip() or None,
            corporate_number=(raw.get(_COL_CORPORATE_NUMBER) or "").strip() or None,
        )


__all__ = ["EdinetCodeRecord", "EdinetCodeResolver"]
