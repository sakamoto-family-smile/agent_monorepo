"""OCR 読み取り — 画像 → テキスト（エンジン）と テキスト → 項目抽出（純粋関数）。

抽出ロジック `extract_fields` はクラウド非依存の純粋関数で、単体テストできる。
エンジン部分は Protocol で抽象化し、default は Mock。本番では Drive OCR /
Cloud Vision を遅延 import で差し込む。

抽出結果はあくまで下書き。保存前に必ず LIFF フォームで人が確認・修正する。
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from app.config import OcrProvider
from app.models import EntryDraft

# 郵便番号: 〒 記号や全角ハイフンにも耐える。
_ZIP_RE = re.compile(r"〒?\s*(\d{3})\s*[-ー－―]?\s*(\d{4})")
# 住所らしい行: 都道府県 + 市区町村などの語を含む。
_ADDR_HINT_RE = re.compile(r"(都|道|府|県|市|区|町|村|郡|丁目|番地|号)")
# 会社・肩書きらしい行（氏名候補から除外する）。
_COMPANY_RE = re.compile(r"(株式会社|有限会社|合同会社|Inc\.?|Corp\.?|部|課|係|マネージャ|代表)")
# 敬称（氏名行から除去する）。
_HONORIFIC_RE = re.compile(r"\s*(様|さん|殿|氏)\s*$")


def _normalize_zip(text: str) -> str:
    """本文から郵便番号を抽出し `NNN-NNNN` に整形。無ければ空文字。"""
    match = _ZIP_RE.search(text)
    if not match:
        return ""
    return f"{match.group(1)}-{match.group(2)}"


def _pick_address(lines: list[str]) -> str:
    """住所ヒント語を含む行のうち最も長いものを住所とみなす。"""
    candidates = [ln for ln in lines if _ADDR_HINT_RE.search(ln)]
    if not candidates:
        return ""
    # 郵便番号だけの行は除外し、最も情報量の多い行を選ぶ。
    candidates = [re.sub(r"〒?\s*\d{3}[-ー－―]?\d{4}", "", c).strip() for c in candidates]
    candidates = [c for c in candidates if c]
    if not candidates:
        return ""
    return max(candidates, key=len)


def _pick_name(lines: list[str], address: str) -> str:
    """氏名候補を推定する。会社・住所・数字を含む行を除外した最初の行。"""
    for line in lines:
        if not line or line == address:
            continue
        if _COMPANY_RE.search(line):
            continue
        if _ADDR_HINT_RE.search(line):
            continue
        if _ZIP_RE.search(line):
            continue
        if re.search(r"\d", line):
            continue  # 電話番号・番地など
        if "@" in line or "http" in line.lower():
            continue
        cleaned = _HONORIFIC_RE.sub("", line).strip()
        if 1 < len(cleaned) <= 20:
            return cleaned
    return ""


def extract_fields(text: str) -> EntryDraft:
    """OCR 生テキストから氏名・郵便番号・住所を推定した下書きを返す。

    誤読前提のベストエフォート。保存前の確認フォームで補正される。
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    zip_code = _normalize_zip(text)
    address = _pick_address(lines)
    name = _pick_name(lines, address)
    return EntryDraft(name=name, zip=zip_code, address=address)


@runtime_checkable
class OcrEngine(Protocol):
    """画像バイト列からテキストを取り出すエンジン。"""

    def recognize(self, image_bytes: bytes) -> str:
        ...


class MockOcrEngine:
    """テスト / ローカル用。あらかじめ設定したテキストを返す。"""

    def __init__(self, text: str = "") -> None:
        self._text = text

    def recognize(self, image_bytes: bytes) -> str:
        return self._text


def build_ocr_engine(provider: OcrProvider) -> OcrEngine:
    """設定に応じた OCR エンジンを構築する。

    `drive` / `vision` は依存が重いので遅延 import。未実装/未設定時は Mock に
    フォールバックして、少なくとも抽出パイプラインは動くようにする。
    """
    if provider == "drive":
        from app.services.ocr_drive import DriveOcrEngine

        return DriveOcrEngine()
    if provider == "vision":
        from app.services.ocr_vision import VisionOcrEngine

        return VisionOcrEngine()
    return MockOcrEngine()


__all__ = [
    "MockOcrEngine",
    "OcrEngine",
    "build_ocr_engine",
    "extract_fields",
]
