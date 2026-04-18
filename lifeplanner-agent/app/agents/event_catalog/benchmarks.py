"""benchmarks/*.yaml をロードし型付きで提供。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_BENCHMARK_DIR = Path(__file__).resolve().parents[3] / "data" / "benchmarks"


def _dec(v: Any) -> Decimal:
    if v is None:
        return Decimal(0)
    return Decimal(str(v))


@dataclass(frozen=True)
class ChildcareBracket:
    income_upto: Decimal | None
    fee: Decimal  # 月額


@dataclass(frozen=True)
class EducationBenchmark:
    # 教育費 (年額)
    preschool_public: Decimal
    preschool_private: Decimal
    elementary_public: Decimal
    elementary_private: Decimal
    junior_high_public: Decimal
    junior_high_private: Decimal
    high_school_public: Decimal
    high_school_private: Decimal
    university_national_public: Decimal
    university_private_humanities: Decimal
    university_private_science: Decimal

    # 出産・児童手当・育休
    birth_one_time_cost: Decimal
    child_allowance_under_3: Decimal
    child_allowance_over_3: Decimal
    child_allowance_third_or_later: Decimal
    parental_leave_first_180d_rate: Decimal
    parental_leave_after_180d_rate: Decimal
    parental_leave_default_duration_months: int

    # 保育料
    childcare_brackets: tuple[ChildcareBracket, ...]
    preschool_free_from_age: int


@dataclass(frozen=True)
class HousingBenchmark:
    closing_cost_ratio: Decimal
    property_tax_rate: Decimal
    annual_maintenance_condo: Decimal
    annual_maintenance_house: Decimal
    mortgage_credit_new_years: int
    mortgage_credit_used_years: int
    mortgage_credit_rate: Decimal
    mortgage_credit_max_balance_general: Decimal
    mortgage_credit_max_balance_energy_saving: Decimal
    default_interest_rate: Decimal
    default_term_years: int


@dataclass(frozen=True)
class VehicleAnnualCost:
    insurance: Decimal
    auto_tax: Decimal
    inspection_annual: Decimal
    fuel: Decimal
    maintenance: Decimal
    parking: Decimal

    @property
    def total(self) -> Decimal:
        return (
            self.insurance
            + self.auto_tax
            + self.inspection_annual
            + self.fuel
            + self.maintenance
            + self.parking
        )


@dataclass(frozen=True)
class VehicleBenchmark:
    annual_by_class: dict[str, VehicleAnnualCost]
    closing_cost_ratio: Decimal
    resale_ratio_by_years: dict[int, Decimal]
    default_hold_years: int


@lru_cache(maxsize=4)
def load_education_benchmark(*, data_dir: Path | None = None) -> EducationBenchmark:
    base = data_dir or _BENCHMARK_DIR
    with (base / "education_cost.yaml").open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    brackets = tuple(
        ChildcareBracket(
            income_upto=_dec(row["income_upto"]) if row.get("income_upto") is not None else None,
            fee=_dec(row["fee"]),
        )
        for row in data["childcare_monthly"]
    )

    return EducationBenchmark(
        preschool_public=_dec(data["preschool"]["public"]),
        preschool_private=_dec(data["preschool"]["private"]),
        elementary_public=_dec(data["elementary"]["public"]),
        elementary_private=_dec(data["elementary"]["private"]),
        junior_high_public=_dec(data["junior_high"]["public"]),
        junior_high_private=_dec(data["junior_high"]["private"]),
        high_school_public=_dec(data["high_school"]["public"]),
        high_school_private=_dec(data["high_school"]["private"]),
        university_national_public=_dec(data["university"]["national_public"]),
        university_private_humanities=_dec(data["university"]["private_humanities"]),
        university_private_science=_dec(data["university"]["private_science"]),
        birth_one_time_cost=_dec(data["birth_one_time_cost"]),
        child_allowance_under_3=_dec(data["child_allowance_monthly"]["under_3"]),
        child_allowance_over_3=_dec(data["child_allowance_monthly"]["over_3"]),
        child_allowance_third_or_later=_dec(data["child_allowance_monthly"]["third_or_later"]),
        parental_leave_first_180d_rate=_dec(data["parental_leave_benefit"]["first_180_days_rate"]),
        parental_leave_after_180d_rate=_dec(data["parental_leave_benefit"]["after_180_days_rate"]),
        parental_leave_default_duration_months=int(
            data["parental_leave_benefit"]["default_duration_months"]
        ),
        childcare_brackets=brackets,
        preschool_free_from_age=int(data["preschool_free_from_age"]),
    )


@lru_cache(maxsize=4)
def load_housing_benchmark(*, data_dir: Path | None = None) -> HousingBenchmark:
    base = data_dir or _BENCHMARK_DIR
    with (base / "housing_cost.yaml").open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    mc = data["mortgage_credit"]
    return HousingBenchmark(
        closing_cost_ratio=_dec(data["closing_cost_ratio"]),
        property_tax_rate=_dec(data["property_tax_rate"]),
        annual_maintenance_condo=_dec(data["annual_maintenance_condo"]),
        annual_maintenance_house=_dec(data["annual_maintenance_house"]),
        mortgage_credit_new_years=int(mc["new_years"]),
        mortgage_credit_used_years=int(mc["used_years"]),
        mortgage_credit_rate=_dec(mc["rate"]),
        mortgage_credit_max_balance_general=_dec(mc["max_balance_general"]),
        mortgage_credit_max_balance_energy_saving=_dec(mc["max_balance_energy_saving"]),
        default_interest_rate=_dec(data["default_interest_rate"]),
        default_term_years=int(data["default_term_years"]),
    )


@lru_cache(maxsize=4)
def load_vehicle_benchmark(*, data_dir: Path | None = None) -> VehicleBenchmark:
    base = data_dir or _BENCHMARK_DIR
    with (base / "vehicle_cost.yaml").open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    annual = {
        class_name: VehicleAnnualCost(
            insurance=_dec(row["insurance"]),
            auto_tax=_dec(row["auto_tax"]),
            inspection_annual=_dec(row["inspection_annual"]),
            fuel=_dec(row["fuel"]),
            maintenance=_dec(row["maintenance"]),
            parking=_dec(row["parking"]),
        )
        for class_name, row in data["annual_costs"].items()
    }
    resale = {int(years): _dec(ratio) for years, ratio in data["resale_ratio_by_years"].items()}
    return VehicleBenchmark(
        annual_by_class=annual,
        closing_cost_ratio=_dec(data["closing_cost_ratio"]),
        resale_ratio_by_years=resale,
        default_hold_years=int(data["default_hold_years"]),
    )
