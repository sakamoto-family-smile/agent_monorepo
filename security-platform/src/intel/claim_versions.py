"""記事の主張の版 (記事の書き方のまま) を、照合に使える形 (個別の版と OSV の range) に直す。

LLM は版を記事の書き方のまま抜き出す (grounding.py で原文にあるか確かめるため)。記事では
"earlier than 1.84.1" "< 2.0" "1.2.0 - 1.2.5" のような範囲の書き方が多いので、決まった書き方だけを
range ({"introduced": ..., "fixed" / "last_affected": ...}) にする。解釈できない書き方は使わない (照合しない)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..detection.versions import is_affected, version_key

_V = r"v?\d[0-9A-Za-z.+_~:-]*"
_BEFORE = r"(?:<|earlier than|before|prior to|older than|lower than|less than|below)"
_UP_TO = r"(?:<=|≤|up to(?: and including)?|through|until)"
_AND_EARLIER = r"(?:and|or) (?:earlier|older|below|prior|lower)"
_AND_LATER = r"(?:and|or) (?:later|newer|above|higher)"
_FROM = r"(?:>=|≥|from)"
_VERSIONS = r"(?:(?:all )?versions? |releases? )?"

# (正規表現, 作る events)。A・B は 1 つ目・2 つ目の版
_PATTERNS: tuple[tuple[re.Pattern[str], tuple[tuple[str, str], ...]], ...] = tuple(
    (re.compile(rf"^{_VERSIONS}{p}$", re.IGNORECASE), events) for p, events in (
        (rf"{_BEFORE}\s*({_V})", (("introduced", "0"), ("fixed", "A"))),
        (rf"{_UP_TO}\s*({_V})", (("introduced", "0"), ("last_affected", "A"))),
        (rf"({_V})\s*{_AND_EARLIER}", (("introduced", "0"), ("last_affected", "A"))),
        (rf"{_FROM}\s*({_V})\s*(?:,|and)?\s*{_BEFORE}\s*({_V})", (("introduced", "A"), ("fixed", "B"))),
        (rf"{_FROM}\s*({_V})\s*(?:,|and|to)?\s*{_UP_TO}\s*({_V})", (("introduced", "A"), ("last_affected", "B"))),
        (rf"({_V})\s*(?:-|–|to|through)\s*({_V})", (("introduced", "A"), ("last_affected", "B"))),
        (rf"(?:{_FROM}\s*({_V})|({_V})\s*{_AND_LATER})", (("introduced", "A"),)),
    )
)
_EXACT = re.compile(rf"^(?:=|==)?\s*({_V})$", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedVersions:
    exact: tuple[str, ...]
    ranges: tuple[dict[str, Any], ...]
    unparsed: tuple[str, ...]

    @property
    def matchable(self) -> bool:
        return bool(self.exact or self.ranges)


def _clean(ecosystem: str, v: str) -> str:
    v = v.rstrip(".,;")
    return v if ecosystem == "Go" or not re.match(r"^v\d", v) else v[1:]


def _valid(ecosystem: str, v: str) -> bool:
    try:
        version_key(ecosystem, v)
    except ValueError as e:
        return "unsupported ecosystem" in str(e)  # 比べられないエコシステムは書き方だけで受け付ける
    return True


def parse(ecosystem: str, versions: tuple[str, ...] | list[str]) -> ParsedVersions:
    """ecosystem は OSV の表記。"""
    exact: list[str] = []
    ranges: list[dict[str, Any]] = []
    unparsed: list[str] = []
    for raw in versions:
        s = " ".join(raw.split())
        m = _EXACT.match(s)
        if m and _valid(ecosystem, v := _clean(ecosystem, m.group(1))):
            exact.append(v)
            continue
        rng = _range(ecosystem, s)
        if rng is None:
            unparsed.append(raw)
        elif rng not in ranges:
            ranges.append(rng)
    return ParsedVersions(tuple(dict.fromkeys(exact)), tuple(ranges), tuple(unparsed))


def _range(ecosystem: str, s: str) -> dict[str, Any] | None:
    for pattern, events in _PATTERNS:
        m = pattern.match(s)
        if m is None:
            continue
        found = [_clean(ecosystem, g) for g in m.groups() if g]
        values = {"A": found[0], "B": found[1] if len(found) > 1 else None}
        out = []
        for kind, ref in events:
            v = values.get(ref, ref)
            if v is None or not _valid(ecosystem, v):
                return None
            out.append({kind: v})
        return {"type": "ECOSYSTEM", "events": out}
    return None


def affects(ecosystem: str, version: str, versions: tuple[str, ...] | list[str]) -> bool:
    """記事の版の書き方で、この版が影響を受けると言えるか (言えなければ False)。"""
    p = parse(ecosystem, versions)
    if not p.matchable:
        return False
    return bool(is_affected(ecosystem, version, list(p.ranges), list(p.exact)))
