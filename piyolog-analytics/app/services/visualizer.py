"""Phase 1.5: matplotlib 純関数によるグラフ描画。

EventRepo.fetch_events_in_range の戻り値タプル列を受け取り、PNG bytes を返す
独立したモジュール。LINE / Postback どちらからも呼び出される想定。

設計判断:
- matplotlib は Agg backend (headless) を強制
- 日本語フォントは Noto Sans CJK JP を fontconfig 名で指定。Docker image 側で
  apt 経由で導入済 (fonts-noto-cjk)。dev 環境で未インストールの場合は font
  fallback が走り、文字化けして警告が出る (壊れない)
- 各関数は (events, period) を受け取り、副作用なく PNG bytes を返す純関数
- 1 関数 1 figure。テーマカラーは module 定数で集中管理
"""

from __future__ import annotations

import io
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

# Agg backend: GUI 不要、PNG 出力専用
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9), "Asia/Tokyo")

# ---- テーマ (Paper Cream パレット) ----

THEME_BG = "#FAF6F0"  # Paper Cream 背景
THEME_FG = "#2B2825"  # Deep Ink 文字
THEME_PEACH = "#F4A896"  # ミルク
THEME_SAGE = "#A9C4A0"  # 睡眠
THEME_BUTTER = "#F5D680"  # 排泄 / heatmap
THEME_SKY = "#A4C5D8"  # 体重・身長 / 頭囲
THEME_GRID = "#E8E2D8"

# 日本語フォント候補。preferred 順に matplotlib に渡し、最初にマッチしたものを使う。
_JP_FONT_CANDIDATES = [
    "Noto Sans CJK JP",
    "Noto Sans JP",
    "IPAexGothic",
    "Hiragino Sans",
    "Yu Gothic",
    "DejaVu Sans",  # 最終 fallback (日本語は出ないが英語 axis ラベル等は描ける)
]


def _setup_matplotlib() -> None:
    """matplotlib のグローバル rcParams をテーマに合わせる (idempotent)。"""
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = _JP_FONT_CANDIDATES
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = THEME_BG
    plt.rcParams["axes.facecolor"] = THEME_BG
    plt.rcParams["axes.edgecolor"] = THEME_FG
    plt.rcParams["axes.labelcolor"] = THEME_FG
    plt.rcParams["axes.titlecolor"] = THEME_FG
    plt.rcParams["xtick.color"] = THEME_FG
    plt.rcParams["ytick.color"] = THEME_FG
    plt.rcParams["text.color"] = THEME_FG
    plt.rcParams["grid.color"] = THEME_GRID
    plt.rcParams["axes.grid"] = True
    plt.rcParams["axes.grid.axis"] = "y"
    plt.rcParams["grid.alpha"] = 0.6
    plt.rcParams["figure.dpi"] = 110


_setup_matplotlib()


# ---- イベントタプルのインデックス (event_repo.fetch_events_in_range と同期) ----
# (event_timestamp, event_date, event_type, volume_ml, left_minutes,
#  right_minutes, sleep_minutes, temperature_c, weight_kg, height_cm,
#  head_circumference_cm, memo)
TS = 0
DATE = 1
TYPE = 2
VOLUME_ML = 3
LEFT_MIN = 4
RIGHT_MIN = 5
SLEEP_MIN = 6
TEMP_C = 7
WEIGHT_KG = 8
HEIGHT_CM = 9
HEAD_CM = 10


def _to_dt(ts: str) -> datetime:
    """ISO8601 (+09:00) を JST datetime に。"""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def _figure_to_png(fig) -> bytes:
    """figure → PNG bytes (in-memory)。close も同時に行う。"""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=THEME_BG, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _empty_chart_png(title: str, message: str = "データがありません") -> bytes:
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.set_title(title, fontsize=14, pad=16)
    ax.text(
        0.5,
        0.5,
        message,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=14,
        color=THEME_FG,
    )
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    return _figure_to_png(fig)


# ---- 個別グラフ ----


def milk_timeline(events: list[tuple[Any, ...]], period: str = "week") -> bytes:
    """ミルク (formula + expressed_milk) の日別合計と回数を棒+折れ線で描画。

    - 棒: 1 日合計 ml (Peach)
    - 折れ線: 3 日移動平均 (深色)
    - 二軸: 右に回数 (gray)
    """
    rows = [
        e
        for e in events
        if e[TYPE] in {"formula", "expressed_milk", "breast_milk"} and e[VOLUME_ML] is not None
    ]
    if not rows:
        return _empty_chart_png(f"ミルク量 ({period})")

    daily_volume: dict[str, float] = defaultdict(float)
    daily_count: dict[str, int] = defaultdict(int)
    for r in rows:
        d = r[DATE]
        daily_volume[d] += r[VOLUME_ML]
        daily_count[d] += 1

    dates = sorted(daily_volume.keys())
    volumes = [daily_volume[d] for d in dates]
    counts = [daily_count[d] for d in dates]

    # 3 日移動平均
    window = 3
    moving_avg: list[float] = []
    for i in range(len(volumes)):
        start = max(0, i - window + 1)
        moving_avg.append(sum(volumes[start : i + 1]) / (i - start + 1))

    fig, ax1 = plt.subplots(figsize=(10, 5))
    x = np.arange(len(dates))
    ax1.bar(x, volumes, color=THEME_PEACH, alpha=0.85, label="日量 (ml)")
    ax1.plot(
        x,
        moving_avg,
        color="#C76A56",
        marker="o",
        linewidth=2,
        markersize=4,
        label="3 日移動平均",
    )
    ax1.set_ylabel("ミルク量 (ml)")
    ax1.set_xticks(x)
    ax1.set_xticklabels([d[5:] for d in dates], rotation=30, ha="right", fontsize=9)

    ax2 = ax1.twinx()
    ax2.plot(
        x,
        counts,
        color="#7A6E62",
        marker="s",
        linestyle="--",
        markersize=4,
        linewidth=1.2,
        alpha=0.7,
        label="回数",
    )
    ax2.set_ylabel("回数")
    ax2.grid(False)

    ax1.set_title(f"ミルク量 ({period})", fontsize=14, pad=12)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper left",
        framealpha=0.9,
        fontsize=9,
    )
    return _figure_to_png(fig)


def sleep_timeline(events: list[tuple[Any, ...]], period: str = "week") -> bytes:
    """日毎の合計睡眠分。WAKE イベントの sleep_minutes を集計し日中(7-19)/夜間で stack。"""
    rows = [e for e in events if e[TYPE] == "wake" and e[SLEEP_MIN] is not None]
    if not rows:
        return _empty_chart_png(f"睡眠時間 ({period})")

    day_total: dict[str, dict[str, float]] = defaultdict(lambda: {"day": 0.0, "night": 0.0})
    for r in rows:
        # WAKE 時刻に sleep_minutes が乗っている。寝た時刻はそれを巻き戻して算出。
        wake_dt = _to_dt(r[TS])
        sleep_min = float(r[SLEEP_MIN])
        sleep_start = wake_dt - timedelta(minutes=sleep_min)
        # 睡眠開始時刻の hour で振り分け (24h 跨ぎは粗い近似)
        bucket = "night" if (sleep_start.hour >= 19 or sleep_start.hour < 7) else "day"
        day_total[r[DATE]][bucket] += sleep_min / 60.0

    dates = sorted(day_total.keys())
    day_hours = [day_total[d]["day"] for d in dates]
    night_hours = [day_total[d]["night"] for d in dates]

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(dates))
    ax.bar(x, night_hours, color=THEME_SAGE, label="夜間 (19-07)")
    ax.bar(
        x,
        day_hours,
        bottom=night_hours,
        color="#D4DFA0",
        alpha=0.9,
        label="日中 (07-19)",
    )
    ax.set_ylabel("時間 (h)")
    ax.set_xticks(x)
    ax.set_xticklabels([d[5:] for d in dates], rotation=30, ha="right", fontsize=9)
    ax.set_title(f"睡眠時間 ({period})", fontsize=14, pad=12)
    ax.legend(loc="upper right", framealpha=0.9, fontsize=9)
    return _figure_to_png(fig)


def weight_height_timeline(events: list[tuple[Any, ...]], period: str = "month") -> bytes:
    """体重・身長の折れ線 + 頭囲 (右軸)。"""
    rows = [e for e in events if e[TYPE] in {"weight", "height", "head_circumference"}]
    if not rows:
        return _empty_chart_png(f"成長記録 ({period})")

    weight_pts: list[tuple[str, float]] = []
    height_pts: list[tuple[str, float]] = []
    head_pts: list[tuple[str, float]] = []
    for r in rows:
        if r[TYPE] == "weight" and r[WEIGHT_KG] is not None:
            weight_pts.append((r[TS], float(r[WEIGHT_KG])))
        elif r[TYPE] == "height" and r[HEIGHT_CM] is not None:
            height_pts.append((r[TS], float(r[HEIGHT_CM])))
        elif r[TYPE] == "head_circumference" and r[HEAD_CM] is not None:
            head_pts.append((r[TS], float(r[HEAD_CM])))

    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1b = None
    if weight_pts:
        wx = [_to_dt(t) for t, _ in weight_pts]
        wy = [v for _, v in weight_pts]
        ax1.plot(wx, wy, color=THEME_PEACH, marker="o", label="体重 (kg)")
    if height_pts:
        hx = [_to_dt(t) for t, _ in height_pts]
        hy = [v for _, v in height_pts]
        # 体重と身長を同 axis にすると目盛差で見えづらいので scale 表示で
        ax1b = ax1.twinx()
        ax1b.plot(hx, hy, color=THEME_SAGE, marker="s", label="身長 (cm)")
        ax1b.set_ylabel("身長 (cm)")
        ax1b.grid(False)
    if head_pts:
        kx = [_to_dt(t) for t, _ in head_pts]
        ky = [v for _, v in head_pts]
        # 頭囲は身長と同 cm なので右の twinx に重ねず、別に薄く重ねる
        ax1.plot(
            kx,
            ky,
            color=THEME_SKY,
            marker="^",
            linestyle="--",
            alpha=0.85,
            label="頭囲 (cm) ※左軸",
        )
    ax1.set_ylabel("体重 (kg) / 頭囲 (cm)")
    ax1.set_title(f"成長記録 ({period})", fontsize=14, pad=12)
    fig.autofmt_xdate()
    handles, labels = ax1.get_legend_handles_labels()
    if ax1b is not None:
        h2, l2 = ax1b.get_legend_handles_labels()
        handles += h2
        labels += l2
    if handles:
        ax1.legend(handles, labels, loc="best", framealpha=0.9, fontsize=9)
    return _figure_to_png(fig)


def feeding_heatmap(events: list[tuple[Any, ...]], period: str = "month") -> bytes:
    """曜日 × 時間帯 (1h 刻み) の授乳ヒートマップ。"""
    rows = [e for e in events if e[TYPE] in {"formula", "expressed_milk", "breast_milk"}]
    if not rows:
        return _empty_chart_png(f"授乳ヒートマップ ({period})")

    # heatmap[weekday][hour]
    heat = np.zeros((7, 24), dtype=int)
    for r in rows:
        dt = _to_dt(r[TS])
        heat[dt.weekday()][dt.hour] += 1

    fig, ax = plt.subplots(figsize=(11, 5))
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
        "butter", ["#FAF6F0", THEME_BUTTER, "#E8A93D"]
    )
    im = ax.imshow(heat, aspect="auto", cmap=cmap)
    weekday_labels = ["月", "火", "水", "木", "金", "土", "日"]
    ax.set_yticks(range(7))
    ax.set_yticklabels(weekday_labels)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h}時" for h in range(0, 24, 2)])
    ax.set_xlabel("時間帯")
    ax.set_title(f"授乳ヒートマップ ({period})", fontsize=14, pad=12)
    cbar = fig.colorbar(im, ax=ax, label="回数")
    cbar.ax.tick_params(labelsize=9)
    ax.grid(False)
    return _figure_to_png(fig)


def dashboard(events: list[tuple[Any, ...]], period: str = "week") -> bytes:
    """4 種を 2x2 サブプロットに集約した一枚絵。"""
    if not events:
        return _empty_chart_png(f"ダッシュボード ({period})")

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    fig.suptitle(f"ダッシュボード ({period})", fontsize=15, y=0.98)

    # 各サブプロットは独立 figure を作って描き、image を貼り付ける方式は採らず
    # 直接 axes に描く軽量版として再実装する。
    _draw_milk_sub(axes[0][0], events)
    _draw_sleep_sub(axes[0][1], events)
    _draw_weight_sub(axes[1][0], events)
    _draw_heatmap_sub(axes[1][1], events)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    return _figure_to_png(fig)


# ---- dashboard 内のサブプロット (簡略版) ----


def _draw_milk_sub(ax, events: list[tuple[Any, ...]]) -> None:
    rows = [
        e
        for e in events
        if e[TYPE] in {"formula", "expressed_milk", "breast_milk"} and e[VOLUME_ML] is not None
    ]
    if not rows:
        ax.set_title("ミルク量")
        ax.text(0.5, 0.5, "データなし", transform=ax.transAxes, ha="center", va="center")
        return
    daily: dict[str, float] = defaultdict(float)
    for r in rows:
        daily[r[DATE]] += r[VOLUME_ML]
    dates = sorted(daily.keys())
    vols = [daily[d] for d in dates]
    ax.bar(range(len(dates)), vols, color=THEME_PEACH)
    ax.set_xticks(range(len(dates)))
    ax.set_xticklabels([d[5:] for d in dates], rotation=30, ha="right", fontsize=8)
    ax.set_title("ミルク量 (ml)")
    ax.set_ylabel("ml")


def _draw_sleep_sub(ax, events: list[tuple[Any, ...]]) -> None:
    rows = [e for e in events if e[TYPE] == "wake" and e[SLEEP_MIN] is not None]
    if not rows:
        ax.set_title("睡眠時間")
        ax.text(0.5, 0.5, "データなし", transform=ax.transAxes, ha="center", va="center")
        return
    daily: dict[str, float] = defaultdict(float)
    for r in rows:
        daily[r[DATE]] += float(r[SLEEP_MIN]) / 60.0
    dates = sorted(daily.keys())
    hours = [daily[d] for d in dates]
    ax.bar(range(len(dates)), hours, color=THEME_SAGE)
    ax.set_xticks(range(len(dates)))
    ax.set_xticklabels([d[5:] for d in dates], rotation=30, ha="right", fontsize=8)
    ax.set_title("睡眠時間 (h)")
    ax.set_ylabel("h")


def _draw_weight_sub(ax, events: list[tuple[Any, ...]]) -> None:
    rows = [e for e in events if e[TYPE] == "weight" and e[WEIGHT_KG] is not None]
    if not rows:
        ax.set_title("体重")
        ax.text(0.5, 0.5, "データなし", transform=ax.transAxes, ha="center", va="center")
        return
    pts = sorted([(r[TS], float(r[WEIGHT_KG])) for r in rows])
    xs = [_to_dt(t) for t, _ in pts]
    ys = [v for _, v in pts]
    ax.plot(xs, ys, color=THEME_SKY, marker="o")
    ax.set_title("体重 (kg)")
    ax.set_ylabel("kg")
    ax.tick_params(axis="x", rotation=30, labelsize=8)


def _draw_heatmap_sub(ax, events: list[tuple[Any, ...]]) -> None:
    rows = [e for e in events if e[TYPE] in {"formula", "expressed_milk", "breast_milk"}]
    if not rows:
        ax.set_title("授乳ヒートマップ")
        ax.text(0.5, 0.5, "データなし", transform=ax.transAxes, ha="center", va="center")
        return
    heat = np.zeros((7, 24), dtype=int)
    for r in rows:
        dt = _to_dt(r[TS])
        heat[dt.weekday()][dt.hour] += 1
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
        "butter", ["#FAF6F0", THEME_BUTTER, "#E8A93D"]
    )
    ax.imshow(heat, aspect="auto", cmap=cmap)
    ax.set_yticks(range(7))
    ax.set_yticklabels(["月", "火", "水", "木", "金", "土", "日"], fontsize=8)
    ax.set_xticks(range(0, 24, 4))
    ax.set_xticklabels([f"{h}" for h in range(0, 24, 4)], fontsize=8)
    ax.set_title("授乳ヒートマップ")
    ax.grid(False)


__all__ = [
    "dashboard",
    "feeding_heatmap",
    "milk_timeline",
    "sleep_timeline",
    "weight_height_timeline",
]
