"""年版税制テーブル YAML のロードと型付きアクセス。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# data/tax_tables/{year}.yaml の既定パス
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "tax_tables"


@dataclass(frozen=True)
class ProgressiveBracket:
    """累進テーブル 1 行分。

    upto: この値以下の部分に適用 (None は上限なし)
    rate: 税率 (例 0.10)
    deduction: 速算控除額 (所得税用。給与所得控除用は offset を使う)
    offset: 控除額の定数 (給与所得控除用; tax 用は 0)
    """

    upto: Decimal | None
    rate: Decimal
    deduction: Decimal = Decimal(0)
    offset: Decimal = Decimal(0)
    flat_deduction: Decimal | None = None  # 低収入層の一律控除


@dataclass(frozen=True)
class TaxTable:
    year: int
    # 給与所得控除
    salary_deduction_brackets: tuple[ProgressiveBracket, ...]
    salary_deduction_cap: Decimal
    # 基礎控除
    basic_deduction_income: Decimal
    basic_deduction_resident: Decimal
    # 所得税
    income_tax_brackets: tuple[ProgressiveBracket, ...]
    reconstruction_surtax_rate: Decimal
    # 住民税
    resident_income_rate: Decimal
    resident_flat_amount: Decimal
    resident_adjustment_deduction: Decimal
    # 社保
    health_insurance_rate: Decimal
    pension_rate: Decimal
    employment_insurance_rate: Decimal
    health_monthly_cap: Decimal
    pension_monthly_cap: Decimal


def _dec(v: Any) -> Decimal:
    """YAML からロードした数値 (int/float/str) を Decimal に寄せる。"""
    if v is None:
        return Decimal(0)
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _parse_salary_brackets(raw: list[dict[str, Any]]) -> tuple[ProgressiveBracket, ...]:
    """給与所得控除ブラケットを tuple 化。最初の行は `deduction` だけを持つ。"""
    out: list[ProgressiveBracket] = []
    for row in raw:
        upto = _dec(row["upto"]) if row.get("upto") is not None else None
        if "rate" in row:
            out.append(
                ProgressiveBracket(
                    upto=upto,
                    rate=_dec(row["rate"]),
                    offset=_dec(row.get("offset", 0)),
                )
            )
        else:
            # 低収入層の一律控除 (rate なし)
            out.append(
                ProgressiveBracket(
                    upto=upto,
                    rate=Decimal(0),
                    flat_deduction=_dec(row["deduction"]),
                )
            )
    return tuple(out)


def _parse_income_brackets(raw: list[dict[str, Any]]) -> tuple[ProgressiveBracket, ...]:
    out: list[ProgressiveBracket] = []
    for row in raw:
        upto = _dec(row["upto"]) if row.get("upto") is not None else None
        out.append(
            ProgressiveBracket(
                upto=upto,
                rate=_dec(row["rate"]),
                deduction=_dec(row.get("deduction", 0)),
            )
        )
    return tuple(out)


@lru_cache(maxsize=8)
def load_tax_table(year: int, *, data_dir: Path | None = None) -> TaxTable:
    """指定年度の税制テーブルをロード。見つからない場合は最新年度にフォールバック。"""
    base_dir = data_dir or _DEFAULT_DATA_DIR
    path = base_dir / f"{year}.yaml"
    if not path.exists():
        # 最新年度ファイルへフォールバック
        candidates = sorted(base_dir.glob("*.yaml"))
        if not candidates:
            raise FileNotFoundError(f"No tax tables found under {base_dir}")
        path = candidates[-1]

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    sal = data["salary_income_deduction"]
    basic = data["basic_deduction"]
    inc = data["income_tax"]
    res = data["resident_tax"]
    si = data["social_insurance"]

    return TaxTable(
        year=int(data["year"]),
        salary_deduction_brackets=_parse_salary_brackets(sal["brackets"]),
        salary_deduction_cap=_dec(sal["cap"]),
        basic_deduction_income=_dec(basic["income_tax"]),
        basic_deduction_resident=_dec(basic["resident_tax"]),
        income_tax_brackets=_parse_income_brackets(inc["brackets"]),
        reconstruction_surtax_rate=_dec(inc["reconstruction_surtax_rate"]),
        resident_income_rate=_dec(res["income_rate"]),
        resident_flat_amount=_dec(res["flat_amount"]),
        resident_adjustment_deduction=_dec(res["adjustment_deduction"]),
        health_insurance_rate=_dec(si["health_insurance_rate"]),
        pension_rate=_dec(si["pension_rate"]),
        employment_insurance_rate=_dec(si["employment_insurance_rate"]),
        health_monthly_cap=_dec(si["health_monthly_cap"]),
        pension_monthly_cap=_dec(si["pension_monthly_cap"]),
    )
