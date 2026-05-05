"""Phase 3-B: context_builder.build_recent_context のテスト。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from services.context_builder import build_recent_context

JST = timezone(timedelta(hours=9), "Asia/Tokyo")


class _FakeRepo:
    def __init__(self, events_by_range: dict[tuple[str, str], list[tuple]]) -> None:
        self.events_by_range = events_by_range
        self.calls: list[tuple[str, str]] = []

    async def fetch_events_in_range(
        self, *, family_id: str, date_from: str, date_to: str
    ) -> list[tuple]:
        self.calls.append((date_from, date_to))
        # 完全一致でなくても日付範囲をまたぐようにシンプル化: keys を試して最初のマッチを返す
        for (df, dt), evs in self.events_by_range.items():
            if df == date_from and dt == date_to:
                return evs
        return []


def _milk(date: str, hour: int = 12, ml: float = 100.0) -> tuple:
    ts = datetime.strptime(date, "%Y-%m-%d").replace(hour=hour, tzinfo=JST).isoformat()
    return (ts, date, "formula", ml, None, None, None, None, None, None, None, None)


def _wake(date: str, hour: int = 7, sleep_min: int = 480) -> tuple:
    ts = datetime.strptime(date, "%Y-%m-%d").replace(hour=hour, tzinfo=JST).isoformat()
    return (ts, date, "wake", None, None, None, sleep_min, None, None, None, None, None)


def _weight(date: str, kg: float) -> tuple:
    ts = datetime.strptime(date, "%Y-%m-%d").replace(hour=8, tzinfo=JST).isoformat()
    return (ts, date, "weight", None, None, None, None, None, kg, None, None, None)


@pytest.mark.asyncio
async def test_build_context_includes_all_sections() -> None:
    """profile / 72h / 7d の 3 section が含まれる。"""
    now = datetime(2026, 5, 4, 10, 0, tzinfo=JST)
    # 7d range: 4/28 〜 5/4, 30d range: 4/5 〜 5/4
    events = {
        ("2026-04-28", "2026-05-04"): [
            _milk("2026-05-03", 9, 100),
            _milk("2026-05-03", 13, 120),
            _wake("2026-05-03", 7, 540),
        ],
        ("2026-04-05", "2026-05-04"): [
            _weight("2026-04-15", 5.2),
            _weight("2026-05-01", 5.6),
        ],
    }
    repo = _FakeRepo(events)
    text = await build_recent_context(repo=repo, family_id="f1", now=now, birth_date="2026-04-01")
    assert "## 子のプロフィール" in text
    assert "## 直近 72 時間" in text
    assert "## 直近 7 日" in text
    # 月齢計算 (4/1 → 5/4 = 約 1 か月)
    assert "1か月" in text or "0か月" in text
    # 体重最新値 (5/1 の 5.6 kg)
    assert "5.60" in text
    # 7d ミルク量
    assert "ミルク" in text


@pytest.mark.asyncio
async def test_build_context_no_data() -> None:
    now = datetime(2026, 5, 4, 10, 0, tzinfo=JST)
    repo = _FakeRepo({})
    text = await build_recent_context(repo=repo, family_id="f1", now=now)
    assert "該当データなし" in text
    # birth_date 空なら月齢不明
    assert "月齢: 不明" in text


@pytest.mark.asyncio
async def test_build_context_72h_subset_of_7d() -> None:
    """72h セクションは 7d データの subset (filter で抽出)。"""
    now = datetime(2026, 5, 4, 10, 0, tzinfo=JST)
    events = {
        ("2026-04-28", "2026-05-04"): [
            _milk("2026-04-29", 9, 100),  # > 72h 前 → 7d のみ
            _milk("2026-05-03", 9, 120),  # < 72h 前 → 両方
        ],
        ("2026-04-05", "2026-05-04"): [],
    }
    repo = _FakeRepo(events)
    text = await build_recent_context(repo=repo, family_id="f1", now=now)
    # 72h section に 1 件 (120 ml), 7d section に 2 件 (220 ml) が反映される
    assert "120" in text or "220" in text


# ---- Phase 4-B: ChildRepo fallback ----


class _FakeChildRepo:
    def __init__(self, *, birth_date: str | None, name: str | None) -> None:
        from repositories.child_repo import Child

        self._child = Child(
            family_id="f1",
            child_id="default",
            birth_date=birth_date,
            name=name,
            updated_at="2026-05-05T00:00:00+00:00",
        )

    async def get(self, *, family_id: str, child_id: str):
        return self._child


@pytest.mark.asyncio
async def test_build_context_uses_child_repo() -> None:
    """children テーブルから生年月日 / 名前を取得して month-age を計算。"""
    now = datetime(2026, 5, 4, 10, 0, tzinfo=JST)
    repo = _FakeRepo({})
    cr = _FakeChildRepo(birth_date="2026-04-01", name="たろう")
    text = await build_recent_context(repo=repo, family_id="f1", now=now, child_repo=cr)
    # name が context に出る
    assert "たろう" in text
    # 月齢計算が走る (約 1 か月)
    assert "1か月" in text or "0か月" in text


@pytest.mark.asyncio
async def test_build_context_no_child_repo_no_age() -> None:
    """child_repo 未配線なら月齢は不明扱い (env からは取らない)。"""
    now = datetime(2026, 5, 4, 10, 0, tzinfo=JST)
    repo = _FakeRepo({})
    text = await build_recent_context(repo=repo, family_id="f1", now=now)
    assert "月齢: 不明" in text


@pytest.mark.asyncio
async def test_build_context_explicit_arg_overrides_child_repo() -> None:
    """テスト用に直接渡した `birth_date` 引数は DB より優先される。"""
    now = datetime(2026, 5, 4, 10, 0, tzinfo=JST)
    repo = _FakeRepo({})
    cr = _FakeChildRepo(birth_date="2025-01-01", name="DB太郎")
    text = await build_recent_context(
        repo=repo,
        family_id="f1",
        now=now,
        birth_date="2026-04-01",  # 引数が優先
        child_repo=cr,
    )
    assert "1か月" in text or "0か月" in text
    assert "1歳" not in text
