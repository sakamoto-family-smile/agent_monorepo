"""財務資料 (有価証券報告書) ドメインのスキーマ・型レジストリ・ラベル辞書。

請求書ドメインと異なる precision リスクを検証対象に含める:
  - **単位スケール** (百万円/千円) — スケール忘れの値ズレ
  - **△ (マイナス) 符号** — 損失の符号取り違え
  - **当期↔前期の列取り違え** — 財務版の C2 (スロット帰属ミス)

当期/前期の取り違えを帰属チェックで捕捉するため、ラベルを period+metric の合成
(例: 「当期売上高」) にし、各ラベルが単一フィールドを所有する構成にする。
"""

from __future__ import annotations

from .schema import FieldType
from .validate.labels import LabelLexicon

# metric キー → 表示名 (ラベル/行見出しに使う)
METRIC_LABELS: dict[str, str] = {
    "net_sales": "売上高",
    "operating_income": "営業利益",
    "ordinary_income": "経常利益",
    "net_income": "純利益",
    "total_assets": "総資産",
    "net_assets": "純資産",
    "equity_ratio": "自己資本比率",
    "eps": "1株当たり利益",
}
PERIOD_LABELS: dict[str, str] = {"current": "当期", "prior": "前期"}

# 百万円スケールの金額系 metric (AMOUNT) と、% / 円の比率系 metric (NUMERIC)
_AMOUNT_METRICS = {
    "net_sales",
    "operating_income",
    "ordinary_income",
    "net_income",
    "total_assets",
    "net_assets",
}
_NUMERIC_METRICS = {"equity_ratio", "eps"}

# 単独フィールド (period を持たない)
_SINGLETONS: dict[str, tuple[FieldType, str]] = {
    "company_name": (FieldType.NAME, "会社名"),
    "edinet_code": (FieldType.CODE, "EDINETコード"),
    "securities_code": (FieldType.CODE, "証券コード"),
    "fiscal_year_end": (FieldType.DATE, "事業年度末"),
    "submission_date": (FieldType.DATE, "提出日"),
}


def _build_field_types() -> dict[str, FieldType]:
    ft: dict[str, FieldType] = {}
    for metric in METRIC_LABELS:
        kind = FieldType.AMOUNT if metric in _AMOUNT_METRICS else FieldType.NUMERIC
        for period in PERIOD_LABELS:
            ft[f"{metric}_{period}"] = kind
    for fid, (kind, _label) in _SINGLETONS.items():
        ft[fid] = kind
    return ft


def _build_labels() -> LabelLexicon:
    lex: dict[str, frozenset[str]] = {}
    for metric, mlabel in METRIC_LABELS.items():
        for period, plabel in PERIOD_LABELS.items():
            lex[f"{plabel}{mlabel}"] = frozenset({f"{metric}_{period}"})
    for fid, (_kind, label) in _SINGLETONS.items():
        lex[label] = frozenset({fid})
    return lex


FINANCIAL_FIELD_TYPES: dict[str, FieldType] = _build_field_types()
FINANCIAL_LABELS: LabelLexicon = _build_labels()


def period_partner(field_id: str) -> str | None:
    """_current ↔ _prior の相方フィールドID。単独フィールドは None。"""
    if field_id.endswith("_current"):
        return field_id[: -len("_current")] + "_prior"
    if field_id.endswith("_prior"):
        return field_id[: -len("_prior")] + "_current"
    return None
