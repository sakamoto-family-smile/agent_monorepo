"""改修の対象の選び方 (planner) と差分検査 (guard)。"""
from __future__ import annotations

from typing import ClassVar

import pytest

from src.common.paths import DataPaths
from src.common.services import Service
from src.detection.lockfiles import Component
from src.detection.matcher import AdvisoryInfo, Match
from src.remediation import guard
from src.remediation.planner import is_major_bump, plan_service
from tests.remediation.helpers import add_finding, detection_db, entry, lock

SVC = Service(id="examplesvc", path="examplesvc/", exposure="external", deployed=True, lockfiles=("uv.lock",),
              auto_remediation=True)


@pytest.fixture
def detection(tmp_path):
    return detection_db(DataPaths(tmp_path / "data"))


@pytest.mark.parametrize(("current", "target", "major"), [
    ("1.2.0", "1.9.3", False), ("1.2.0", "2.0.0", True), ("0.4.1", "0.4.9", False), ("0.4.1", "0.5.0", True),
    ("2", "2.1", False), ("1.0.0rc1", "1.0.0", False),
])
def test_is_major_bump(current, target, major):
    assert is_major_bump(current, target) is major


def test_plan_takes_the_highest_fix_per_package(detection):
    add_finding(detection, "f1", "examplesvc", "examplelib", "1.2.0", "1.2.5")
    add_finding(detection, "f2", "examplesvc", "examplelib", "1.2.0", "1.4.0", priority="P3")
    add_finding(detection, "f3", "examplesvc", "Sample_HTTP", "3.0.0", "3.0.2", priority="P1")
    plan = plan_service(detection, SVC, "P3", set())
    assert [(b.name, b.current, b.target, b.priority, b.finding_ids) for b in plan.bumps] == [
        ("sample-http", "3.0.0", "3.0.2", "P1", ("f3",)),  # 優先度の高い順
        ("examplelib", "1.2.0", "1.4.0", "P2", ("f1", "f2")),
    ]
    assert plan.manual  # P1 を含むので人がマージする


def test_plan_skips_major_attempted_and_out_of_scope(detection):
    add_finding(detection, "f1", "examplesvc", "examplelib", "1.2.0", "2.0.0")  # メジャー
    add_finding(detection, "f2", "examplesvc", "demoparse", "0.4.0", "0.4.2")  # 前に失敗
    add_finding(detection, "f3", "examplesvc", "toyyaml", "5.0", "5.1", priority="P4")  # 優先度の範囲外
    add_finding(detection, "f4", "examplesvc", "imageonly", "1.0", "1.1", source_kind="image")  # 本番イメージだけ
    add_finding(detection, "f5", "examplesvc", "npmthing", "1.0", "1.1", ecosystem="npm",
                lockfile="examplesvc/package-lock.json")
    add_finding(detection, "f6", "examplesvc", "nofix", "1.0", None)
    add_finding(detection, "f7", "examplesvc", "closedlib", "1.0", "1.1", state="resolved")
    add_finding(detection, "f8", "examplesvc", "forked", "1.0", "1.1")
    add_finding(detection, "f9", "examplesvc", "forked", "1.5", "1.6", advisory="EXAMPLE-f9")
    plan = plan_service(detection, SVC, "P3", {("demoparse", "0.4.2")})
    assert plan.bumps == ()
    assert {(s.name, s.reason) for s in plan.skipped} == {
        ("examplelib", "major"), ("demoparse", "attempted"), ("forked", "multiple_versions")}
    assert not plan.manual


def test_plan_none_without_uv_lock(detection):
    add_finding(detection, "f1", "examplesvc", "examplelib", "1.2.0", "1.2.5")
    assert plan_service(detection, Service(**{**SVC.model_dump(), "lockfiles": ()}), "P3", set()) is None
    assert plan_service(detection, SVC, "P1", set()) is None  # P2 は範囲外


# ── guard ─────────────────────────────────────────────────────────────────
OLD = lock({"examplelib": "1.2.0", "samplehttp": "3.0.0", "demoparse": "0.4.0"})


def test_guard_passes_a_clean_bump():
    new = lock({"examplelib": "1.4.0", "samplehttp": "3.0.0", "demoparse": "0.4.0"})
    r = guard.check(OLD, new, {"examplelib": "1.4.0"})
    assert r.ok, r.problems
    assert [(c.name, c.old, c.new) for c in r.changes] == [("examplelib", ("1.2.0",), ("1.4.0",))]


def test_guard_allows_a_few_other_minor_changes():
    new = lock({"examplelib": "1.4.0", "samplehttp": "3.0.1", "demoparse": "0.4.0", "newdep": "1.0.0"},
               direct=("demoparse", "examplelib", "samplehttp"),
               entries={"examplelib": entry("examplelib", "1.4.0", deps=("newdep",))})
    r = guard.check(OLD, new, {"examplelib": "1.4.0"})
    assert r.ok, r.problems


@pytest.mark.parametrize(("new", "problem"), [
    (lock({"examplelib": "1.3.0", "samplehttp": "3.0.0", "demoparse": "0.4.0"}), "1.4.0 に上がっていない"),
    (lock({"examplelib": "1.4.0", "samplehttp": "3.0.0", "demoparse": "0.4.0"},
          entries={"samplehttp": entry("samplehttp", "3.0.0", salt="swapped")}), "版が同じなのに中身が変わった"),
    (lock({"examplelib": "1.4.0", "samplehttp": "4.0.0", "demoparse": "0.4.0"}), "メジャーバージョンが上がった"),
    (lock({"examplelib": "1.4.0", "samplehttp": "3.0.0", "demoparse": "0.5.0"}), "メジャーバージョンが上がった"),
    (lock({"examplelib": "1.4.0", "samplehttp": "3.0.0", "demoparse": "0.4.0"},
          entries={"examplelib": entry("examplelib", "1.4.0", host="evil.example")}), "配布ファイルの取得先"),
    (lock({"examplelib": "1.4.0", "samplehttp": "3.0.0", "demoparse": "0.4.0"},
          entries={"examplelib": entry("examplelib", "1.4.0", registry="https://mirror.example/simple")}),
     "取得元が"),
    (lock({"examplelib": "1.4.0", "samplehttp": "3.0.0", "demoparse": "0.4.0"}).replace(
        'requires-python = ">=3.12"', 'requires-python = ">=3.11"'), "lockfile の設定"),
    (lock({"examplelib": "1.4.0", "samplehttp": "3.0.0", "demoparse": "0.4.0",
           **{f"extra{i}": "1.0" for i in range(6)}}, direct=("demoparse", "examplelib", "samplehttp")), "上限 5"),
    ("not toml = [", "読めない"),
])
def test_guard_rejects(new, problem):
    r = guard.check(OLD, new, {"examplelib": "1.4.0"})
    assert not r.ok
    assert any(problem in p for p in r.problems), r.problems


class FakeMatcher:
    """名前と版 → (Advisory の ID, kind, 修正版) の表で照合する。"""

    table: ClassVar[dict[tuple[str, str], list[tuple[str, str, str | None]]]] = {}

    def __init__(self, _engine) -> None:
        pass

    def match(self, components: list[Component]):
        out = []
        for c in components:
            for adv, kind, fixed in self.table.get((c.name, c.version), []):
                info = AdvisoryInfo(adv, kind, None, None, None, False, None, ())
                out.append(Match(c, info, (adv,), fixed))
        return out, None


@pytest.mark.parametrize(("table", "ok", "problem"), [
    ({("examplelib", "1.2.0"): [("EX-1", "vulnerable", "1.4.0")]}, True, None),
    ({("examplelib", "1.4.0"): [("EX-2", "vulnerable", "1.5.0")]}, False, "新しく当たる"),
    ({("examplelib", "1.2.0"): [("EX-1", "vulnerable", "1.5.0")],
      ("examplelib", "1.4.0"): [("EX-1", "vulnerable", "1.5.0")]}, False, "が残る"),
    ({("examplelib", "1.2.0"): [("EX-1", "vulnerable", None)],
      ("examplelib", "1.4.0"): [("EX-1", "vulnerable", None)]}, True, None),  # 修正版なしは止めない
    ({("examplelib", "1.4.0"): [("EX-3", "malicious", None)]}, False, "悪性"),
])
def test_guard_rechecks_new_versions_against_advisories(monkeypatch, table, ok, problem):
    monkeypatch.setattr(guard, "Matcher", FakeMatcher)
    monkeypatch.setattr(FakeMatcher, "table", table)
    new = lock({"examplelib": "1.4.0", "samplehttp": "3.0.0", "demoparse": "0.4.0"})
    r = guard.check(OLD, new, {"examplelib": "1.4.0"}, intel=object())  # type: ignore[arg-type]
    assert r.ok is ok, r.problems
    if problem:
        assert any(problem in p for p in r.problems)


def test_guard_accepts_revision_upgrade_and_equivalent_versions():
    new = lock({"examplelib": "1.4", "samplehttp": "3.0.0", "demoparse": "0.4.0"}, revision=4)
    r = guard.check(OLD, new, {"examplelib": "1.4.0"})  # 1.4 と 1.4.0 は同じ版
    assert r.ok, r.problems
    down = lock({"examplelib": "1.4.0", "samplehttp": "3.0.0", "demoparse": "0.4.0"}, revision=2)
    assert any("下がった" in p for p in guard.check(OLD, down, {"examplelib": "1.4.0"}).problems)


@pytest.mark.parametrize(("table", "target", "skip"), [
    ({}, "1.4.0", None),  # Finding の修正版で直る
    ({("examplelib", "1.4.0"): [("EX-1", "vulnerable", "1.4.2")]}, "1.4.2", None),  # 別の範囲にも当たる
    ({("examplelib", "1.4.0"): [("EX-1", "vulnerable", "1.4.2")],
      ("examplelib", "1.4.2"): [("EX-2", "vulnerable", "1.6.0")]}, "1.6.0", None),  # 2 段
    ({("examplelib", "1.4.0"): [("EX-1", "vulnerable", "2.0.1")]}, None, "major"),  # 直る版はメジャーの先
    ({("examplelib", v): [("EX-1", "vulnerable", w)] for v, w in
      [("1.4.0", "1.4.1"), ("1.4.1", "1.4.2"), ("1.4.2", "1.4.3"), ("1.4.3", "1.4.4"), ("1.4.4", "1.4.5"),
       ("1.4.5", "1.4.6")]}, None, "unresolved"),
    ({("examplelib", "1.4.0"): [("EX-1", "vulnerable", None)]}, "1.4.0", None),  # 修正版なしは追わない
])
def test_refine_raises_target_until_advisories_are_fixed(detection, monkeypatch, table, target, skip):
    from src.remediation import planner
    monkeypatch.setattr(planner, "Matcher", FakeMatcher)
    monkeypatch.setattr(FakeMatcher, "table", table)
    add_finding(detection, "f1", "examplesvc", "examplelib", "1.2.0", "1.4.0")
    plan = planner.refine(plan_service(detection, SVC, "P3", set()), object())  # type: ignore[arg-type]
    assert [b.target for b in plan.bumps] == ([target] if target else [])
    assert [s.reason for s in plan.skipped] == ([skip] if skip else [])
