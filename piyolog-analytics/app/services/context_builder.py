"""Phase 3: LLM への RECENT CONTEXT を構築する純関数。

ユーザーの質問に対して LLM が「最近のミルク量」「最近の体重」等を踏まえて
答えられるよう、直近 72 時間 + 7 日のサマリ + 最新の体重 / 体温を 500-1500 tokens
程度の日本語テキストに圧縮する。

設計判断:
- LLM への流量を抑えるため、生イベント全件は渡さない
- 「直近 72h サマリ」+「直近 7 日サマリ」+「最新測定値」の 3 点に絞る
- analytics-platform の summary 機能は使わず、event_repo から直接集計 (依存最小化)
- 出力は **常に同じ section 順** で書き出し、LLM の prompt caching が効くよう構造化
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9), "Asia/Tokyo")

# event_repo の戻り値タプル index (visualizer.py と同じ)
_TS = 0
_DATE = 1
_TYPE = 2
_VOLUME_ML = 3
_LEFT_MIN = 4
_RIGHT_MIN = 5
_SLEEP_MIN = 6
_TEMP_C = 7
_WEIGHT_KG = 8
_HEIGHT_CM = 9
_HEAD_CM = 10


def _parse_birth_date(raw: str) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _age_label(birth: date | None, today: date) -> str:
    """生年月日 → 「0 歳 2 か月 14 日」風のラベル。birth が None なら空文字。"""
    if birth is None:
        return ""
    if today < birth:
        return ""
    months = (today.year - birth.year) * 12 + (today.month - birth.month)
    if today.day < birth.day:
        months -= 1
    years = months // 12
    months = months % 12
    # 簡易 days 計算 (近似でよい)
    days_into_month = today.day - birth.day if today.day >= birth.day else 0
    parts = []
    if years > 0:
        parts.append(f"{years}歳")
    parts.append(f"{months}か月")
    parts.append(f"{days_into_month}日")
    return "".join(parts)


def _summarize_period(events: Iterable[tuple], *, label: str) -> str:
    """events タプル列を section 1 つの日本語要約に変換。"""
    formula_count = 0
    formula_ml = 0.0
    breast_count = 0
    breast_left = 0
    breast_right = 0
    expressed_count = 0
    expressed_ml = 0.0
    sleep_minutes_total = 0
    pee_count = 0
    poo_count = 0
    bath_count = 0
    medicine_count = 0
    type_counter: Counter[str] = Counter()

    for e in events:
        type_counter[e[_TYPE]] += 1
        et = e[_TYPE]
        if et == "formula" and e[_VOLUME_ML] is not None:
            formula_count += 1
            formula_ml += e[_VOLUME_ML]
        elif et == "expressed_milk" and e[_VOLUME_ML] is not None:
            expressed_count += 1
            expressed_ml += e[_VOLUME_ML]
        elif et == "breast_milk":
            breast_count += 1
            breast_left += e[_LEFT_MIN] or 0
            breast_right += e[_RIGHT_MIN] or 0
        elif et == "wake" and e[_SLEEP_MIN] is not None:
            sleep_minutes_total += e[_SLEEP_MIN]
        elif et == "pee":
            pee_count += 1
        elif et == "poo":
            poo_count += 1
        elif et == "bath":
            bath_count += 1
        elif et == "medicine":
            medicine_count += 1

    lines = [f"## {label}"]
    if formula_count > 0:
        lines.append(f"- ミルク: {formula_count} 回 / {int(formula_ml)} ml")
    if expressed_count > 0:
        lines.append(f"- 搾母乳: {expressed_count} 回 / {int(expressed_ml)} ml")
    if breast_count > 0:
        lines.append(f"- 母乳: {breast_count} 回 / 左 {breast_left} 分 + 右 {breast_right} 分")
    if sleep_minutes_total > 0:
        h = sleep_minutes_total // 60
        m = sleep_minutes_total % 60
        lines.append(f"- 睡眠合計: {h} 時間 {m} 分 ({sleep_minutes_total} 分)")
    if pee_count > 0:
        lines.append(f"- おしっこ: {pee_count} 回")
    if poo_count > 0:
        lines.append(f"- うんち: {poo_count} 回")
    if bath_count > 0:
        lines.append(f"- お風呂: {bath_count} 回")
    if medicine_count > 0:
        lines.append(f"- お薬: {medicine_count} 回")
    if len(lines) == 1:
        lines.append("- 該当データなし")
    return "\n".join(lines)


def _latest_metric(
    events: Iterable[tuple], *, event_type: str, value_idx: int
) -> tuple[str, float] | None:
    """events 中で event_type にマッチする最新の (timestamp, value)。"""
    latest: tuple[str, float] | None = None
    for e in events:
        if e[_TYPE] == event_type and e[value_idx] is not None:
            if latest is None or e[_TS] > latest[0]:
                latest = (e[_TS], float(e[value_idx]))
    return latest


async def build_recent_context(
    *,
    repo,
    family_id: str,
    now: datetime | None = None,
    birth_date: str | None = None,
    child_repo=None,
    child_id: str = "default",
    child_name: str | None = None,
) -> str:
    """LLM に渡す RECENT CONTEXT 文字列を返す。

    Sections:
      - 子のプロフィール (月齢 + 直近の体重・身長・頭囲)
      - 直近 72 時間サマリ
      - 直近 7 日サマリ

    `birth_date` / `child_name` が空かつ `child_repo` が渡されていれば、
    children テーブルから (family_id, child_id) で fallback する。
    Phase 4-B で追加 (Phase 3 の env-only セットアップとの後方互換維持)。
    """
    # env / 引数指定が空なら DB から fallback
    if (not birth_date or not child_name) and child_repo is not None:
        try:
            child = await child_repo.get(family_id=family_id, child_id=child_id)
        except Exception:
            logger.exception("child_repo.get failed; skipping DB fallback")
            child = None
        if child is not None:
            if not birth_date and child.birth_date:
                birth_date = child.birth_date
            if not child_name and child.name:
                child_name = child.name
    n = (now or datetime.now(UTC)).astimezone(JST)
    today_jst = n.date()
    span_72h_from = (n - timedelta(hours=72)).date().isoformat()
    span_7d_from = (n - timedelta(days=6)).date().isoformat()
    today_iso = today_jst.isoformat()

    # 7 日分を一括取得 (72h はその subset)
    events_7d = await repo.fetch_events_in_range(
        family_id=family_id,
        date_from=span_7d_from,
        date_to=today_iso,
    )
    # 30 日分: 体重・身長等の最新値検索用
    span_30d_from = (n - timedelta(days=29)).date().isoformat()
    events_30d = await repo.fetch_events_in_range(
        family_id=family_id,
        date_from=span_30d_from,
        date_to=today_iso,
    )

    # 72h subset
    events_72h = [e for e in events_7d if e[_DATE] >= span_72h_from]

    # 子のプロフィール
    profile_lines = ["## 子のプロフィール"]
    if child_name:
        profile_lines.append(f"- 名前: {child_name}")
    age = _age_label(_parse_birth_date(birth_date or ""), today_jst)
    if age:
        profile_lines.append(f"- 月齢: {age}")
    else:
        profile_lines.append("- 月齢: 不明 (生年月日が未設定。⚙️ 設定から登録してください)")
    weight = _latest_metric(events_30d, event_type="weight", value_idx=_WEIGHT_KG)
    height = _latest_metric(events_30d, event_type="height", value_idx=_HEIGHT_CM)
    head = _latest_metric(events_30d, event_type="head_circumference", value_idx=_HEAD_CM)
    temp = _latest_metric(events_30d, event_type="temperature", value_idx=_TEMP_C)
    if weight:
        profile_lines.append(f"- 最新体重: {weight[1]:.2f} kg ({weight[0][:10]} 計測)")
    if height:
        profile_lines.append(f"- 最新身長: {height[1]:.1f} cm ({height[0][:10]} 計測)")
    if head:
        profile_lines.append(f"- 最新頭囲: {head[1]:.1f} cm ({head[0][:10]} 計測)")
    if temp:
        profile_lines.append(f"- 最新体温: {temp[1]:.1f} °C ({temp[0][:10]} 計測)")

    sections = [
        "\n".join(profile_lines),
        _summarize_period(events_72h, label=f"直近 72 時間 ({span_72h_from} 〜 {today_iso})"),
        _summarize_period(events_7d, label=f"直近 7 日 ({span_7d_from} 〜 {today_iso})"),
    ]
    header = (
        "あなたが piyolog の運営する家族の育児データアシスタントを助けるための\n"
        f"RECENT CONTEXT (生成時刻 JST: {n.strftime('%Y-%m-%d %H:%M')}) です。\n"
        "ユーザーの質問が一般的な相談なら、以下のサマリを参考に文脈に沿って答えてください。\n"
        "より細かいデータが必要なら `query_events` tool を呼んで取得してください。\n"
    )
    return header + "\n\n" + "\n\n".join(sections)


__all__ = ["build_recent_context"]
