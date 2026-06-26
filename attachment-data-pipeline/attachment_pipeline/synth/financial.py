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


def generate_sample(sample_id: int) -> GoldSample:
    rng = random.Random(sample_id * 31 + 1)
    b = _Builder()

    company = rng.choice(_COMPANIES)
    edinet = f"E{rng.randint(1, 99999):05d}"
    sec_code = f"{rng.randint(1000, 9999)}"
    fy_year = 2024 + rng.randint(0, 2)
    submit_day = rng.randint(10, 28)

    # 当期/前期の金額 (円)。前期は当期の 0.8〜1.1 倍。営業/経常/純利益は赤字もあり得る。
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

    equity_ratio = {"current": round(rng.uniform(30, 65), 1),
                    "prior": round(rng.uniform(30, 65), 1)}
    eps = {"current": round(rng.uniform(50, 400), 2),
           "prior": round(rng.uniform(50, 400), 2)}

    # ── テキスト組み立て ──
    b.add("有価証券報告書\n\n")
    b.add_label("会社名", FINANCIAL_LABELS["会社名"])
    b.add(": ")
    b.add_field("company_name", company)
    b.add("\n")
    b.add_label("EDINETコード", FINANCIAL_LABELS["EDINETコード"])
    b.add(": ")
    b.add_field("edinet_code", edinet)
    b.add("\n")
    b.add_label("証券コード", FINANCIAL_LABELS["証券コード"])
    b.add(": ")
    b.add_field("securities_code", sec_code)
    b.add("\n")
    b.add_label("事業年度末", FINANCIAL_LABELS["事業年度末"])
    b.add(": ")
    b.add_field("fiscal_year_end", f"{fy_year}年3月31日")
    b.add("\n")
    b.add_label("提出日", FINANCIAL_LABELS["提出日"])
    b.add(": ")
    b.add_field("submission_date", f"{fy_year}年6月{submit_day}日")
    b.add("\n\n主要な経営指標等の推移:\n")

    def emit_metric(metric: str, render_current: str, render_prior: str) -> None:
        mlabel = METRIC_LABELS[metric]
        for period, render in (("current", render_current), ("prior", render_prior)):
            label = f"{PERIOD_LABELS[period]}{mlabel}"
            b.add("  ")
            b.add_label(label, FINANCIAL_LABELS[label])
            b.add(": ")
            b.add_field(f"{metric}_{period}", render)
            b.add("\n")

    for metric in _AMOUNT_METRICS:
        emit_metric(
            metric,
            _fmt_million(values_yen[f"{metric}_current"]),
            _fmt_million(values_yen[f"{metric}_prior"]),
        )
    emit_metric("equity_ratio", f"{equity_ratio['current']}%", f"{equity_ratio['prior']}%")
    emit_metric("eps", f"{eps['current']:.2f}円", f"{eps['prior']:.2f}円")

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
