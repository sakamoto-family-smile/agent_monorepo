"""優先度の判定のテスト。"""
from __future__ import annotations

from src.common.services import Service
from src.detection.lockfiles import Component
from src.detection.matcher import AdvisoryInfo
from src.detection.triage import triage

PROD = Service(id="api", path="api/", exposure="external", deployed=True)
IDLE = Service(id="tool", path="tool/", exposure="none", deployed=False)


def adv(**kw) -> AdvisoryInfo:
    base = {"advisory_id": "X", "kind": "vulnerability", "summary": None, "severity": None,
            "cvss_score": None, "kev": False, "epss": None, "cves": ()}
    return AdvisoryInfo(**(base | kw))


def comp(scope: str = "runtime") -> Component:
    return Component("PyPI", "lib", "1.0", "pkg:pypi/lib@1.0", True, scope)  # type: ignore[arg-type]


def test_base_priorities():
    assert triage(adv(kind="malicious"), comp(), PROD).priority == "P1"
    assert triage(adv(kev=True, severity="LOW"), comp(), PROD).priority == "P1"
    assert triage(adv(severity="CRITICAL"), comp(), PROD).priority == "P2"
    assert triage(adv(severity="MEDIUM", epss=0.33), comp(), PROD).priority == "P2"
    assert triage(adv(severity="HIGH"), comp(), PROD).priority == "P3"
    assert triage(adv(severity="MEDIUM"), comp(), PROD).priority == "P4"
    assert triage(adv(), comp(), PROD).reasons == ("深刻度 なし",)


def test_context_lowers_one_step_but_not_p1():
    assert triage(adv(severity="CRITICAL"), comp("dev"), PROD).priority == "P3"
    assert triage(adv(severity="CRITICAL"), comp("dev"), IDLE).priority == "P3"  # 重ねて下げない
    assert triage(adv(severity="HIGH"), comp(), IDLE).priority == "P4"
    assert triage(adv(severity="LOW"), comp("dev"), PROD).priority == "P4"
    assert triage(adv(kind="malicious"), comp("dev"), IDLE).priority == "P1"
    assert triage(adv(kev=True), comp(), IDLE).priority == "P1"
