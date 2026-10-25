"""OSV レコード (https://ossf.github.io/osv-schema/) を intel.db の行へ変換する。

LLM は使わない。構造化ソースなのでコードで決定的に変換する (メモ FR-I02)。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from cvss import CVSS2, CVSS3, CVSS4
from cvss.exceptions import CVSSError

logger = logging.getLogger(__name__)

CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$")
SUMMARY_MAX = 500


@dataclass(frozen=True)
class Affected:
    ecosystem: str | None
    name: str | None
    purl: str | None
    ranges: list[dict[str, Any]]
    fixed: list[str]
    versions_count: int


@dataclass(frozen=True)
class OsvRecord:
    record_id: str
    aliases: tuple[str, ...]
    upstream: tuple[str, ...]
    summary: str | None
    published_at: str | None
    modified_at: str | None
    withdrawn: bool
    cvss_vector: str | None
    cvss_score: float | None
    severity_label: str | None
    affected: tuple[Affected, ...]
    content_hash: str

    @property
    def db_prefix(self) -> str:
        return self.record_id.split("-", 1)[0]

    @property
    def cves(self) -> frozenset[str]:
        ids = (self.record_id, *self.aliases, *self.upstream)
        return frozenset(i for i in ids if CVE_RE.match(i))


def is_cve(value: str) -> bool:
    return bool(CVE_RE.match(value))


def content_hash(raw: dict[str, Any]) -> str:
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cvss_base_score(kind: str, vector: str) -> float | None:
    try:
        if kind == "CVSS_V4":
            return float(CVSS4(vector).base_score)
        if kind == "CVSS_V3":
            return float(CVSS3(vector).scores()[0])
        if kind == "CVSS_V2":
            return float(CVSS2(vector).scores()[0])
    except (CVSSError, ValueError, KeyError, IndexError):  # 不正なベクタは無視
        logger.debug("unparseable %s vector: %s", kind, vector)
    return None


def _best_cvss(severities: list[dict[str, Any]]) -> tuple[str | None, float | None]:
    best: tuple[str | None, float | None] = (None, None)
    for s in severities:
        vector = s.get("score")
        if not isinstance(vector, str):
            continue
        score = cvss_base_score(str(s.get("type", "")), vector)
        if score is not None and (best[1] is None or score > best[1]):
            best = (vector, score)
    return best


def _parse_affected(entry: dict[str, Any]) -> Affected:
    pkg = entry.get("package") or {}
    ranges = entry.get("ranges") or []
    fixed = sorted(
        {
            ev["fixed"]
            for r in ranges
            for ev in r.get("events") or []
            if isinstance(ev, dict) and ev.get("fixed")
        }
    )
    return Affected(
        ecosystem=pkg.get("ecosystem"),
        name=pkg.get("name"),
        purl=pkg.get("purl"),
        ranges=ranges,
        fixed=fixed,
        versions_count=len(entry.get("versions") or []),
    )


def _summary(raw: dict[str, Any]) -> str | None:
    text = raw.get("summary") or raw.get("details") or ""
    text = " ".join(text.split())
    return text[:SUMMARY_MAX] or None


# Red Hat 系 (AlmaLinux 等) は深刻度を構造化フィールドでなく summary の先頭 ("Important: ...") に書く
_SUMMARY_SEVERITY = re.compile(r"^(Critical|Important|Moderate|Low):\s")
_SUMMARY_SEVERITY_LABELS = {"Critical": "CRITICAL", "Important": "HIGH", "Moderate": "MEDIUM", "Low": "LOW"}


def severity_label_from_summary(summary: str | None) -> str | None:
    m = _SUMMARY_SEVERITY.match(summary or "")
    return _SUMMARY_SEVERITY_LABELS[m.group(1)] if m else None


def parse_record(raw: dict[str, Any]) -> OsvRecord:
    record_id = raw["id"]
    affected_raw = raw.get("affected") or []
    severities = list(raw.get("severity") or [])
    for a in affected_raw:
        severities.extend(a.get("severity") or [])
    vector, score = _best_cvss(severities)
    label = (raw.get("database_specific") or {}).get("severity")
    if not isinstance(label, str):
        label = severity_label_from_summary(raw.get("summary"))
    return OsvRecord(
        record_id=record_id,
        aliases=tuple(sorted(set(raw.get("aliases") or []) - {record_id})),
        upstream=tuple(sorted(set(raw.get("upstream") or []) - {record_id})),
        summary=_summary(raw),
        published_at=raw.get("published"),
        modified_at=raw.get("modified"),
        withdrawn=bool(raw.get("withdrawn")),
        cvss_vector=vector,
        cvss_score=score,
        severity_label=label if isinstance(label, str) else None,
        affected=tuple(_parse_affected(a) for a in affected_raw),
        content_hash=content_hash(raw),
    )
