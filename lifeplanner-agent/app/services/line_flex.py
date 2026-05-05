"""Flex Message JSON の生成。

SDK 依存のない純関数で Flex JSON (dict) を返す:
  - `narrative_bubble`: /summarize / /compare の返信で使う見出し + 本文バブル
  - `scenarios_carousel`: /scenarios の返信で使うシナリオ一覧カルーセル
  - `summary_bubble`: /summary の返信 (PR 2)
  - `networth_bubble`: /networth の返信 (PR 2)
  - `anomalies_bubble`: /anomalies の返信 (PR 2)

LINE の上限:
  - carousel は最大 12 bubble (ただし実用上 10 以下が安全)
  - 1 text component は 2000 文字まで
  - alt_text は 400 文字まで
"""

from __future__ import annotations

from decimal import Decimal

_HEADER_COLOR = "#1E40AF"
_SUBTLE_COLOR = "#6B7280"
_POSITIVE_COLOR = "#059669"
_NEGATIVE_COLOR = "#DC2626"
_DIVIDER_COLOR = "#E5E7EB"

_MAX_NARRATIVE_CHARS = 1800
_MAX_DESC_CHARS = 200
_TOP_CATEGORIES_IN_BUBBLE = 5


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def narrative_bubble(*, title: str, body_text: str) -> dict:
    """見出し + 本文の 1 bubble。"""
    return {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": _HEADER_COLOR,
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": _truncate(title, 60),
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "md",
                    "wrap": True,
                }
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": _truncate(body_text, _MAX_NARRATIVE_CHARS),
                    "wrap": True,
                    "size": "sm",
                }
            ],
        },
    }


def _scenario_bubble(*, scenario_id: int, name: str, description: str | None) -> dict:
    contents: list[dict] = [
        {"type": "text", "text": f"#{scenario_id}", "color": _SUBTLE_COLOR, "size": "xs"},
        {
            "type": "text",
            "text": _truncate(name, 60),
            "weight": "bold",
            "size": "md",
            "wrap": True,
        },
    ]
    if description:
        contents.append(
            {
                "type": "text",
                "text": _truncate(description, _MAX_DESC_CHARS),
                "wrap": True,
                "color": "#444444",
                "size": "xs",
            }
        )
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": contents,
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "color": _HEADER_COLOR,
                    "action": {
                        "type": "message",
                        "label": "要約",
                        "text": f"/summarize {scenario_id}",
                    },
                }
            ],
        },
    }


def scenarios_carousel(scenarios: list[tuple[int, str, str | None]]) -> dict:
    """scenarios: `(id, name, description)` のリスト。

    10 件までを 1 carousel に詰める。超過分は呼び出し側で切り落とすこと。
    """
    limited = scenarios[:10]
    return {
        "type": "carousel",
        "contents": [
            _scenario_bubble(scenario_id=s[0], name=s[1], description=s[2])
            for s in limited
        ],
    }


# ---------------------------------------------------------------------------
# PR 2: 分析コマンドの Flex bubble
# ---------------------------------------------------------------------------


def _yen(amount: Decimal | int | float) -> str:
    """¥1,234,567 形式で日本円表示。負値も対応。"""
    val = int(round(Decimal(amount)))
    sign = "-" if val < 0 else ""
    return f"{sign}¥{abs(val):,}"


def _signed_yen(amount: Decimal | int | float) -> str:
    """+¥1,234 / -¥1,234 形式 (符号付き、ネット表示用)。"""
    val = int(round(Decimal(amount)))
    if val >= 0:
        return f"+¥{val:,}"
    return f"-¥{abs(val):,}"


def _percent(rate: Decimal | int | float, *, precision: int = 1) -> str:
    """0.333 → 33.3%。"""
    return f"{Decimal(rate) * 100:.{precision}f}%"


def _kv_row(label: str, value: str, *, value_color: str | None = None) -> dict:
    """ラベル: 値 の 1 行 (左ラベル + 右寄せ値)。"""
    value_box: dict = {
        "type": "text",
        "text": value,
        "size": "sm",
        "align": "end",
        "weight": "bold",
        "wrap": False,
    }
    if value_color:
        value_box["color"] = value_color
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {"type": "text", "text": label, "size": "sm", "color": _SUBTLE_COLOR},
            value_box,
        ],
    }


def _section_header(text: str) -> dict:
    """カード内のセクション見出し (例: 内訳 / 資産 / 負債)。"""
    return {
        "type": "text",
        "text": text,
        "weight": "bold",
        "size": "xs",
        "color": _SUBTLE_COLOR,
        "margin": "md",
    }


def _separator() -> dict:
    return {"type": "separator", "margin": "md", "color": _DIVIDER_COLOR}


def summary_bubble(
    *,
    period_label: str,
    total_income: Decimal,
    total_expense: Decimal,
    net: Decimal,
    savings_rate: Decimal,
    fixed: Decimal,
    variable: Decimal,
    top_categories: list[tuple[str, Decimal]],
) -> dict:
    """`/summary` の応答バブル。"""
    net_color = _POSITIVE_COLOR if net >= 0 else _NEGATIVE_COLOR
    body_contents: list[dict] = [
        _kv_row("収入", _yen(total_income)),
        _kv_row("支出", _yen(total_expense)),
        _kv_row("ネット", _signed_yen(net), value_color=net_color),
        _kv_row("貯蓄率", _percent(savings_rate), value_color=net_color),
        _separator(),
        _section_header("固定 / 変動"),
        _kv_row("固定費", _yen(fixed)),
        _kv_row("変動費", _yen(variable)),
    ]
    if top_categories:
        body_contents.append(_separator())
        body_contents.append(
            _section_header(f"カテゴリ Top {len(top_categories)}")
        )
        for cat, amount in top_categories:
            body_contents.append(_kv_row(_truncate(cat, 16), _yen(amount)))

    return {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": _HEADER_COLOR,
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": _truncate(f"📊 サマリ ({period_label})", 60),
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "md",
                    "wrap": True,
                }
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": body_contents,
        },
    }


def networth_bubble(
    *,
    as_of_label: str,
    total_assets: Decimal,
    total_liabilities: Decimal,
    net_worth: Decimal,
    by_kind_assets: dict[str, Decimal],
    by_kind_liabilities: dict[str, Decimal],
) -> dict:
    """`/networth` の応答バブル。"""
    net_color = _POSITIVE_COLOR if net_worth >= 0 else _NEGATIVE_COLOR
    body_contents: list[dict] = [
        _kv_row("総資産", _yen(total_assets), value_color=_POSITIVE_COLOR),
        _kv_row("総負債", _yen(total_liabilities), value_color=_NEGATIVE_COLOR),
        _separator(),
        _kv_row("純資産", _yen(net_worth), value_color=net_color),
    ]
    if by_kind_assets:
        body_contents.append(_separator())
        body_contents.append(_section_header("資産"))
        for kind, value in sorted(
            by_kind_assets.items(), key=lambda kv: kv[1], reverse=True
        ):
            body_contents.append(_kv_row(_truncate(kind, 16), _yen(value)))
    if by_kind_liabilities:
        body_contents.append(_separator())
        body_contents.append(_section_header("負債"))
        for kind, balance in sorted(
            by_kind_liabilities.items(), key=lambda kv: kv[1], reverse=True
        ):
            body_contents.append(_kv_row(_truncate(kind, 16), _yen(balance)))

    return {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": _HEADER_COLOR,
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": _truncate(f"💰 純資産 ({as_of_label} 時点)", 60),
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "md",
                    "wrap": True,
                }
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": body_contents,
        },
    }


def anomalies_bubble(
    *,
    target_month_label: str,
    anomalies: list[tuple[str, Decimal, Decimal, Decimal]],
    history_months: int,
) -> dict:
    """`/anomalies` の応答バブル。

    anomalies: (category, expense, mean, z_score) のリスト。z_score 降順想定。
    空なら「異常なし」表示。
    """
    body_contents: list[dict] = [
        _kv_row("対象月", target_month_label),
        _kv_row("履歴", f"直近 {history_months} ヶ月"),
        _separator(),
    ]
    if not anomalies:
        body_contents.append(
            {
                "type": "text",
                "text": "✅ 過去平均から 3σ を超えるカテゴリはありません。",
                "wrap": True,
                "size": "sm",
                "color": _POSITIVE_COLOR,
            }
        )
    else:
        body_contents.append(_section_header(f"検出 ({len(anomalies)} 件)"))
        for cat, expense, mean, z_score in anomalies[:_TOP_CATEGORIES_IN_BUBBLE]:
            body_contents.append(
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "margin": "sm",
                    "contents": [
                        {
                            "type": "text",
                            "text": _truncate(cat, 24),
                            "weight": "bold",
                            "size": "sm",
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": f"今月 {_yen(expense)}",
                                    "size": "xs",
                                    "color": _NEGATIVE_COLOR,
                                },
                                {
                                    "type": "text",
                                    "text": f"平均 {_yen(mean)} / z={z_score:.1f}σ",
                                    "size": "xs",
                                    "color": _SUBTLE_COLOR,
                                    "align": "end",
                                },
                            ],
                        },
                    ],
                }
            )
    return {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": _HEADER_COLOR,
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": _truncate(f"⚠️ 異常検知 ({target_month_label})", 60),
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "md",
                    "wrap": True,
                }
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": body_contents,
        },
    }
