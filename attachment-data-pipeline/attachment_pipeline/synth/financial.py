"""合成-but-grounded 有価証券報告書 (財務サマリ) 生成器。

主要な経営指標を 当期/前期 の2期分、百万円スケール・△負数・%・円 を交えて生成し、
各値の正解 span とラベル位置を記録する。当期↔前期の取り違えを帰属チェックで検証
できるよう、各行を period+metric の合成ラベル (例: 「当期売上高」) で見出す。

seed 固定で完全再現可能。金額は百万円単位で表示 (内部の正解値は実数の円)。
"""

from __future__ import annotations

import random

from ..schema_financial import (
    FINANCIAL_FIELD_TYPES,
    FINANCIAL_LABELS,
    METRIC_LABELS,
    PERIOD_LABELS,
)
from .generator import GoldSample, LabelOccurrence

_COMPANIES = [
    "株式会社サンプル工業",
    "日本テクノロジー株式会社",
    "東洋食品ホールディングス株式会社",
    "中央電機株式会社",
]
_MILLION = 1_000_000

# field_id → 所有ラベル (全ラベルが単一フィールド所有なので一意に逆引きできる)。
_LABEL_OF: dict[str, str] = {
    next(iter(owners)): label for label, owners in FINANCIAL_LABELS.items()
}

# metric → (表示単位サフィックス, スケール, 値生成レンジ, 小数桁)
_AMOUNT_METRICS = ("net_sales", "operating_income", "ordinary_income", "net_income",
                   "total_assets", "net_assets")


class _Builder:
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


def _fmt_million(yen: int) -> str:
    """円の正解値を百万円表示の原文文字列にする (例: -12,345,000,000 → △12,345百万円)。"""
    millions = abs(yen) // _MILLION
    sign = "△" if yen < 0 else ""
    return f"{sign}{millions:,}百万円"


def compute_displays(rng: random.Random) -> tuple[dict[str, str], dict[str, str], dict[str, int]]:
    """単独フィールド・指標フィールドの表示文字列を生成する。

    戻り値: (singletons, metrics, amount_values_yen)。amount_values_yen は長文版が
    距離撹乱 (distractor) の数値を作るのに使う。
    """
    company = rng.choice(_COMPANIES)
    fy_year = 2024 + rng.randint(0, 2)
    singletons = {
        "company_name": company,
        "edinet_code": f"E{rng.randint(1, 99999):05d}",
        "securities_code": f"{rng.randint(1000, 9999)}",
        "fiscal_year_end": f"{fy_year}年3月31日",
        "submission_date": f"{fy_year}年6月{rng.randint(10, 28)}日",
    }

    values_yen: dict[str, int] = {}
    for metric in _AMOUNT_METRICS:
        base = rng.randint(50, 2000) * 1000 * _MILLION  # 数百億〜2兆規模
        cur = base
        prior = int(base * rng.uniform(0.8, 1.1)) // _MILLION * _MILLION
        if metric in ("operating_income", "ordinary_income", "net_income"):
            cur = cur // rng.randint(8, 20)
            prior = prior // rng.randint(8, 20)
            if rng.random() < 0.25:  # 前期赤字
                prior = -prior
        values_yen[f"{metric}_current"] = cur
        values_yen[f"{metric}_prior"] = prior

    metrics: dict[str, str] = {fid: _fmt_million(v) for fid, v in values_yen.items()}
    for period in ("current", "prior"):
        metrics[f"equity_ratio_{period}"] = f"{round(rng.uniform(30, 65), 1)}%"
        metrics[f"eps_{period}"] = f"{round(rng.uniform(50, 400), 2):.2f}円"
    return singletons, metrics, values_yen


def emit_header(b: _Builder, singletons: dict[str, str]) -> None:
    """表紙ヘッダ (会社名・コード・日付) を出力。"""
    for fid in ("company_name", "edinet_code", "securities_code", "fiscal_year_end",
                "submission_date"):
        label = _LABEL_OF[fid]
        b.add_label(label, FINANCIAL_LABELS[label])
        b.add(": ")
        b.add_field(fid, singletons[fid])
        b.add("\n")


def emit_summary(b: _Builder, metrics: dict[str, str]) -> None:
    """「主要な経営指標等の推移」ブロックを出力。"""
    order = list(_AMOUNT_METRICS) + ["equity_ratio", "eps"]
    for metric in order:
        mlabel = METRIC_LABELS[metric]
        for period in ("current", "prior"):
            label = f"{PERIOD_LABELS[period]}{mlabel}"
            b.add("  ")
            b.add_label(label, FINANCIAL_LABELS[label])
            b.add(": ")
            b.add_field(f"{metric}_{period}", metrics[f"{metric}_{period}"])
            b.add("\n")


def generate_sample(sample_id: int) -> GoldSample:
    rng = random.Random(sample_id * 31 + 1)
    singletons, metrics, _ = compute_displays(rng)

    b = _Builder()
    b.add("有価証券報告書\n\n")
    emit_header(b, singletons)
    b.add("\n主要な経営指標等の推移:\n")
    emit_summary(b, metrics)

    return GoldSample(
        sample_id=sample_id,
        text=b.text(),
        spans=b.spans,
        field_types=dict(FINANCIAL_FIELD_TYPES),
        record=None,
        labels=b.labels,
    )


def generate_dataset(start: int, end: int) -> list[GoldSample]:
    return [generate_sample(i) for i in range(start, end)]
