"""Flex Message JSON の生成。

SDK 依存のない純関数で Flex JSON (dict) を返す:
  - `funds_ranking_carousel`: `/api/funds/recommend` のレスポンスを LINE 上で見せる
  - `screener_ranking_carousel`: `/api/screen` の上位銘柄一覧
  - `analysis_summary_bubble`: 個別株分析結果の本文

LINE の上限:
  - carousel は最大 12 bubble (実用上 10 以下が安全)
  - 1 text component は 2000 文字まで
  - alt_text は 400 文字まで
"""

from __future__ import annotations

from typing import Any

_HEADER_COLOR_PRIMARY = "#1E40AF"
_HEADER_COLOR_ACCENT = "#0F766E"
_SUBTLE_COLOR = "#6B7280"

_MAX_RANK_BUBBLES = 10
_MAX_RATIONALE_LINES = 4
_MAX_NARRATIVE_CHARS = 1800


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# 投資信託レコメンド (funds)
# ---------------------------------------------------------------------------


def _fund_bubble(candidate: dict[str, Any]) -> dict:
    """1 ファンド分の bubble。candidate は FundCandidate.model_dump()。"""
    rank = candidate.get("rank", 0)
    ticker = candidate.get("ticker", "?")
    name = candidate.get("name") or ticker
    score = candidate.get("score", 0)
    ret_h = candidate.get("return_horizon_pct")
    vol = candidate.get("volatility_pct")
    dd = candidate.get("max_drawdown_pct")

    metric_lines: list[str] = []
    if ret_h is not None:
        metric_lines.append(f"期間リターン: {ret_h:+.1f}%")
    if vol is not None:
        metric_lines.append(f"年率σ: {vol:.1f}%")
    if dd is not None:
        metric_lines.append(f"最大DD: {dd:.1f}%")

    rationale = list(candidate.get("rationale", []) or [])[:_MAX_RATIONALE_LINES]

    body_contents: list[dict] = [
        {
            "type": "text",
            "text": f"#{rank} {ticker}",
            "weight": "bold",
            "size": "lg",
            "color": _HEADER_COLOR_PRIMARY,
        },
        {
            "type": "text",
            "text": _truncate(name, 60),
            "size": "sm",
            "color": _SUBTLE_COLOR,
            "wrap": True,
        },
        {
            "type": "separator",
            "margin": "md",
        },
        {
            "type": "text",
            "text": f"スコア: {score}",
            "weight": "bold",
            "margin": "md",
        },
    ]
    if metric_lines:
        body_contents.append(
            {
                "type": "text",
                "text": "\n".join(metric_lines),
                "size": "xs",
                "color": "#444444",
                "wrap": True,
                "margin": "sm",
            }
        )
    if rationale:
        body_contents.append(
            {
                "type": "text",
                "text": "\n".join(f"• {_truncate(r, 80)}" for r in rationale),
                "size": "xs",
                "wrap": True,
                "margin": "md",
            }
        )

    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": body_contents,
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": _HEADER_COLOR_PRIMARY,
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "詳細分析",
                        "text": f"分析 {ticker}",
                    },
                }
            ],
        },
    }


def funds_ranking_carousel(candidates: list[dict[str, Any]]) -> dict:
    """投資信託ランキングを carousel として返す。"""
    limited = candidates[:_MAX_RANK_BUBBLES]
    return {
        "type": "carousel",
        "contents": [_fund_bubble(c) for c in limited],
    }


# ---------------------------------------------------------------------------
# 短期上昇候補スクリーナー (screener)
# ---------------------------------------------------------------------------


def _screener_bubble(candidate: dict[str, Any]) -> dict:
    rank = candidate.get("rank", 0)
    ticker = candidate.get("ticker", "?")
    score = candidate.get("score", 0)
    rsi = candidate.get("rsi_14")
    spike = candidate.get("volume_spike")
    chg = candidate.get("price_change_pct")
    signals = list(candidate.get("signals", []) or [])[:4]

    metric_lines: list[str] = []
    if rsi is not None:
        metric_lines.append(f"RSI: {rsi:.1f}")
    if spike is not None:
        metric_lines.append(f"出来高: x{spike:.1f}")
    if chg is not None:
        metric_lines.append(f"5日: {chg:+.1f}%")

    body_contents: list[dict] = [
        {
            "type": "text",
            "text": f"#{rank} {ticker}",
            "weight": "bold",
            "size": "lg",
            "color": _HEADER_COLOR_ACCENT,
        },
        {
            "type": "text",
            "text": f"スコア: {score}",
            "weight": "bold",
            "margin": "md",
        },
    ]
    if metric_lines:
        body_contents.append(
            {
                "type": "text",
                "text": " / ".join(metric_lines),
                "size": "xs",
                "color": "#444444",
                "wrap": True,
                "margin": "sm",
            }
        )
    if signals:
        body_contents.append(
            {
                "type": "text",
                "text": "\n".join(f"• {_truncate(s, 80)}" for s in signals),
                "size": "xs",
                "wrap": True,
                "margin": "md",
            }
        )

    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": body_contents,
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": _HEADER_COLOR_ACCENT,
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "詳細分析",
                        "text": f"分析 {ticker}",
                    },
                }
            ],
        },
    }


def screener_ranking_carousel(candidates: list[dict[str, Any]]) -> dict:
    limited = candidates[:_MAX_RANK_BUBBLES]
    return {
        "type": "carousel",
        "contents": [_screener_bubble(c) for c in limited],
    }


# ---------------------------------------------------------------------------
# 個別株分析サマリ (analyze)
# ---------------------------------------------------------------------------


def analysis_summary_bubble(*, ticker: str, company_name: str | None, body_text: str) -> dict:
    title = company_name or ticker
    return {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": _HEADER_COLOR_PRIMARY,
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": _truncate(f"{title} ({ticker}) 分析", 60),
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
