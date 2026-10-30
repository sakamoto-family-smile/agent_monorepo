"""Finding の優先度と対応期限。

| 優先度 | 条件 | 期限 |
|---|---|---|
| P1 | 悪性パッケージ、または KEV 掲載 (実際に悪用されている) | 1 日 |
| P2 | Critical、または EPSS が EPSS_HIGH 以上 | 7 日 |
| P3 | High | 30 日 |
| P4 | それ以外 (Medium・Low・深刻度なし) | なし |

P1 以外は、次のどれかなら 1 段下げる (重ねては下げない)。
- dev 依存からしか届かない (本番では読み込まれない)
- 本番で稼働しておらず外部にも公開していないサービス
- 開発 PC のツール (外部に公開しておらず、使うのは本人だけ)
悪性パッケージは入れた時点 (開発機・CI) で被害が出るので下げない。

OS パッケージ (Debian) で修正版がまだ無いものは、P1 以外は P4 (期限なし) にする。
こちらで打てる手が無く、期限を付けても超過が積み上がるだけなので。修正版が出れば
次の照合で本来の優先度に戻り、そこから期限を数える。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..common.services import Service
from .lockfiles import Component
from .matcher import AdvisoryInfo
from .versions import DEBIAN_PREFIX

PRIORITIES = ("P1", "P2", "P3", "P4")
EPSS_HIGH = 0.1
DUE = {"P1": timedelta(days=1), "P2": timedelta(days=7), "P3": timedelta(days=30), "P4": None}


@dataclass(frozen=True)
class Triage:
    priority: str
    reasons: tuple[str, ...]


def _base(adv: AdvisoryInfo) -> tuple[str, str]:
    if adv.kind == "malicious":
        return "P1", "悪性パッケージ"
    if adv.kev:
        return "P1", "KEV 掲載 (悪用を確認)"
    if adv.severity == "CRITICAL":
        return "P2", "深刻度 Critical"
    if adv.epss is not None and adv.epss >= EPSS_HIGH:
        return "P2", f"EPSS {adv.epss:.0%} (悪用の見込みが高い)"
    if adv.severity == "HIGH":
        return "P3", "深刻度 High"
    return "P4", f"深刻度 {adv.severity.title() if adv.severity else 'なし'}"


def triage(
    adv: AdvisoryInfo, component: Component, service: Service, fixed_version: str | None = None,
) -> Triage:
    priority, reason = _base(adv)
    reasons = [reason]
    if priority != "P1" and fixed_version is None and component.ecosystem.startswith(DEBIAN_PREFIX):
        if priority != "P4":
            reasons.append("Debian で未修正 (P4 に下げる)")
        return Triage("P4", tuple(reasons))
    if priority != "P1":
        if component.scope == "dev":
            reasons.append("dev 依存のみ (1 段下げ)")
        elif service.kind == "host":
            reasons.append("開発 PC のツール (1 段下げ)")
        elif not service.deployed and service.exposure == "none":
            reasons.append("未稼働・非公開のサービス (1 段下げ)")
        if len(reasons) > 1:
            priority = PRIORITIES[min(PRIORITIES.index(priority) + 1, len(PRIORITIES) - 1)]
    return Triage(priority, tuple(reasons))


def due_at(priority: str, start: datetime) -> datetime | None:
    delta = DUE[priority]
    return start + delta if delta else None
