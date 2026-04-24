"""期間集計とテキストサマリ生成。

方針:
  - SQLite の `event_date` (JST) を基準に期間を切り出す
  - 集計は Python 側で回す (件数 〜 千オーダーなので SQL GROUP BY を増やすより読みやすい)
  - 出力は LINE 返信向けの 1 メッセージ (4,900 char 以内)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from repositories.event_repo import EventRepo

JST = timezone(timedelta(hours=9), "Asia/Tokyo")


# ---------------------------------------------------------------------------
# 期間決定ヘルパ
# ---------------------------------------------------------------------------


def today_jst(now: datetime | None = None) -> date:
    """現在の JST 日付 (依存注入可能)。"""
    n = now or datetime.now(JST)
    return n.astimezone(JST).date()


def resolve_period(
    period: str,
    *,
    now: datetime | None = None,
    custom_from: str | None = None,
    custom_to: str | None = None,
) -> tuple[date, date, str]:
    """期間種別 → (from, to, 表示ラベル)。"""
    base = today_jst(now)
    if period == "today":
        return base, base, f"{base:%Y/%m/%d}"
    if period == "yesterday":
        d = base - timedelta(days=1)
        return d, d, f"{d:%Y/%m/%d}"
    if period == "week":
        start = base - timedelta(days=6)
        return start, base, f"{start:%Y/%m/%d} 〜 {base:%Y/%m/%d}"
    if period == "month":
        start = base.replace(day=1)
        return start, base, f"{start:%Y/%m/%d} 〜 {base:%Y/%m/%d}"
    if period == "period" and custom_from and custom_to:
        f = datetime.strptime(custom_from, "%Y-%m-%d").date()
        t = datetime.strptime(custom_to, "%Y-%m-%d").date()
        if f > t:
            f, t = t, f
        return f, t, f"{f:%Y/%m/%d} 〜 {t:%Y/%m/%d}"
    raise ValueError(f"unknown period: {period}")


# ---------------------------------------------------------------------------
# 集計
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PeriodSummary:
    label: str
    date_from: str
    date_to: str
    days: int
    formula_count: int
    formula_total_ml: float
    expressed_milk_count: int
    expressed_milk_total_ml: float
    breast_milk_count: int
    breast_milk_left_minutes: int
    breast_milk_right_minutes: int
    sleep_total_minutes: int
    sleep_day_minutes: int                # 07:00–19:00 に含まれる睡眠時間
    sleep_night_minutes: int              # それ以外 (19:00–翌07:00)
    pee_count: int
    poo_count: int
    baby_food_count: int
    bath_count: int
    medicine_count: int
    latest_temperature_c: float | None
    latest_temperature_at: str | None
    latest_weight_kg: float | None
    latest_weight_at: str | None
    latest_height_cm: float | None
    latest_height_at: str | None
    latest_head_circumference_cm: float | None
    latest_head_circumference_at: str | None
    total_events: int


async def summarize(
    *,
    repo: EventRepo,
    family_id: str,
    period: str,
    now: datetime | None = None,
    custom_from: str | None = None,
    custom_to: str | None = None,
) -> PeriodSummary:
    d_from, d_to, label = resolve_period(
        period, now=now, custom_from=custom_from, custom_to=custom_to
    )
    rows = await repo.fetch_events_in_range(
        family_id=family_id,
        date_from=d_from.isoformat(),
        date_to=d_to.isoformat(),
    )
    return _aggregate(rows, label=label, d_from=d_from, d_to=d_to)


def _aggregate(
    rows: list[tuple],
    *,
    label: str,
    d_from: date,
    d_to: date,
) -> PeriodSummary:
    formula_count = 0
    formula_total = 0.0
    expressed_count = 0
    expressed_total = 0.0
    bm_count = 0
    bm_left = 0
    bm_right = 0
    sleep_total = 0
    sleep_day = 0
    sleep_night = 0
    pee = 0
    poo = 0
    baby_food = 0
    bath = 0
    medicine = 0
    latest_temp: tuple[float, str] | None = None
    latest_weight: tuple[float, str] | None = None
    latest_height: tuple[float, str] | None = None
    latest_head: tuple[float, str] | None = None

    for row in rows:
        (
            ts,
            _date,
            et,
            volume_ml,
            left_m,
            right_m,
            sleep_m,
            temp_c,
            weight_kg,
            height_cm,
            head_cm,
            _memo,
        ) = row

        if et == "formula":
            formula_count += 1
            if volume_ml is not None:
                formula_total += float(volume_ml)
        elif et == "expressed_milk":
            expressed_count += 1
            if volume_ml is not None:
                expressed_total += float(volume_ml)
        elif et == "breast_milk":
            bm_count += 1
            if left_m is not None:
                bm_left += int(left_m)
            if right_m is not None:
                bm_right += int(right_m)
        elif et == "wake":
            if sleep_m is not None:
                minutes = int(sleep_m)
                sleep_total += minutes
                # 起床時刻が 07:00〜19:00 なら日中睡眠、それ以外は夜間扱い
                hour = _hour_of_iso(ts)
                if 7 <= hour < 19:
                    sleep_day += minutes
                else:
                    sleep_night += minutes
        elif et == "pee":
            pee += 1
        elif et == "poo":
            poo += 1
        elif et == "baby_food":
            baby_food += 1
        elif et == "bath":
            bath += 1
        elif et == "medicine":
            medicine += 1
        elif et == "temperature":
            if temp_c is not None:
                latest_temp = (float(temp_c), ts)
        elif et == "weight":
            if weight_kg is not None:
                latest_weight = (float(weight_kg), ts)
        elif et == "height":
            if height_cm is not None:
                latest_height = (float(height_cm), ts)
        elif et == "head_circumference":
            if head_cm is not None:
                latest_head = (float(head_cm), ts)

    days = (d_to - d_from).days + 1
    return PeriodSummary(
        label=label,
        date_from=d_from.isoformat(),
        date_to=d_to.isoformat(),
        days=days,
        formula_count=formula_count,
        formula_total_ml=formula_total,
        expressed_milk_count=expressed_count,
        expressed_milk_total_ml=expressed_total,
        breast_milk_count=bm_count,
        breast_milk_left_minutes=bm_left,
        breast_milk_right_minutes=bm_right,
        sleep_total_minutes=sleep_total,
        sleep_day_minutes=sleep_day,
        sleep_night_minutes=sleep_night,
        pee_count=pee,
        poo_count=poo,
        baby_food_count=baby_food,
        bath_count=bath,
        medicine_count=medicine,
        latest_temperature_c=latest_temp[0] if latest_temp else None,
        latest_temperature_at=latest_temp[1] if latest_temp else None,
        latest_weight_kg=latest_weight[0] if latest_weight else None,
        latest_weight_at=latest_weight[1] if latest_weight else None,
        latest_height_cm=latest_height[0] if latest_height else None,
        latest_height_at=latest_height[1] if latest_height else None,
        latest_head_circumference_cm=latest_head[0] if latest_head else None,
        latest_head_circumference_at=latest_head[1] if latest_head else None,
        total_events=len(rows),
    )


def _hour_of_iso(ts_iso: str) -> int:
    try:
        return datetime.fromisoformat(ts_iso).astimezone(JST).hour
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# テキストフォーマッタ
# ---------------------------------------------------------------------------


def _fmt_minutes(m: int) -> str:
    hours, mins = divmod(m, 60)
    return f"{hours}時間{mins}分" if hours else f"{mins}分"


def _fmt_hm(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        return datetime.fromisoformat(iso).astimezone(JST).strftime("%m/%d %H:%M")
    except ValueError:
        return "-"


def render_summary_text(s: PeriodSummary) -> str:
    """LINE 返信用にテキスト整形。"""
    if s.total_events == 0:
        return (
            f"📅 {s.label} のサマリ\n\n"
            "この期間は記録がありません。\n"
            "ぴよログから .txt を送ると取り込みます。"
        )

    lines: list[str] = [f"📅 {s.label} のサマリ"]
    if s.days > 1:
        lines.append(f"  ({s.days} 日間 / 記録 {s.total_events} 件)")
    lines.append("")

    # ミルク
    if s.formula_count or s.expressed_milk_count:
        parts: list[str] = []
        if s.formula_count:
            parts.append(f"ミルク {s.formula_count}回 {int(s.formula_total_ml)}ml")
        if s.expressed_milk_count:
            parts.append(
                f"搾母乳 {s.expressed_milk_count}回 {int(s.expressed_milk_total_ml)}ml"
            )
        lines.append("🍼 " + " / ".join(parts))

    # 母乳
    if s.breast_milk_count:
        lines.append(
            f"🤱 母乳 {s.breast_milk_count}回 / 左{s.breast_milk_left_minutes}分 右{s.breast_milk_right_minutes}分"
        )

    # 睡眠
    if s.sleep_total_minutes:
        if s.days == 1:
            lines.append(
                f"💤 睡眠 {_fmt_minutes(s.sleep_total_minutes)}"
                f" (日中 {_fmt_minutes(s.sleep_day_minutes)} / 夜間 {_fmt_minutes(s.sleep_night_minutes)})"
            )
        else:
            avg = s.sleep_total_minutes // max(s.days, 1)
            lines.append(
                f"💤 睡眠 合計 {_fmt_minutes(s.sleep_total_minutes)} (1日平均 {_fmt_minutes(avg)})"
            )

    # 排泄
    excretion = []
    if s.pee_count:
        excretion.append(f"おしっこ {s.pee_count}回")
    if s.poo_count:
        excretion.append(f"うんち {s.poo_count}回")
    if excretion:
        lines.append("💧 " + " / ".join(excretion))

    # 離乳食 / 入浴 / 投薬
    misc = []
    if s.baby_food_count:
        misc.append(f"離乳食 {s.baby_food_count}回")
    if s.bath_count:
        misc.append(f"お風呂 {s.bath_count}回")
    if s.medicine_count:
        misc.append(f"お薬 {s.medicine_count}回")
    if misc:
        lines.append("🍽️ " + " / ".join(misc))

    # 身体計測 (最新値)
    if s.latest_temperature_c is not None:
        lines.append(
            f"🌡️ 体温 {s.latest_temperature_c:.1f}°C (最終 {_fmt_hm(s.latest_temperature_at)})"
        )
    if s.latest_weight_kg is not None:
        lines.append(f"⚖️ 体重 {s.latest_weight_kg:.2f}kg (最終 {_fmt_hm(s.latest_weight_at)})")
    if s.latest_height_cm is not None:
        lines.append(f"📏 身長 {s.latest_height_cm:.1f}cm (最終 {_fmt_hm(s.latest_height_at)})")
    if s.latest_head_circumference_cm is not None:
        lines.append(
            f"🧢 頭囲 {s.latest_head_circumference_cm:.1f}cm"
            f" (最終 {_fmt_hm(s.latest_head_circumference_at)})"
        )

    return "\n".join(lines)
