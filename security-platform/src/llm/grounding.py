"""LLM の抜き出しを原文と突き合わせる (決定的。LLM は使わない)。

LLM は記事にない名前や版を作り出すことがある。次をすべて満たす主張だけを grounded にする:
- quote (根拠の 1 文) が記事の本文にそのまま含まれる
- パッケージ名が記事に含まれる
版・識別子 (CVE など) は記事に含まれるものだけ残し、落としたものは notes に書く。
比較は NFKC・大文字小文字・空白・引用符の違いを無視して行う。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
_SPACE = re.compile(r"\s+")


_V_PREFIX = re.compile(r"(?<![0-9a-z])v(?=\d)")


def normalize(s: str) -> str:
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", s).translate(_QUOTES).casefold()).strip()


def has_version(src: str, version: str) -> bool:
    """src は normalize 済み。"1.0" が "1.0.3" の一部として当たらないように前後の区切りを見る (v 付きも同じ扱い)。"""
    v = _V_PREFIX.sub("", normalize(version))
    return re.search(rf"(?<![0-9a-z.]){re.escape(v)}(?!\.?[0-9a-z])", _V_PREFIX.sub("", src)) is not None


@dataclass(frozen=True)
class GroundedClaim:
    ecosystem: str
    package: str
    versions: tuple[str, ...]
    kind: str
    identifiers: tuple[str, ...]
    quote: str
    grounded: bool
    notes: tuple[str, ...]


def ground(source: str, claim: dict[str, Any]) -> GroundedClaim:
    """source は LLM に渡したのと同じ記事 (タイトルと本文)。"""
    src = normalize(source)
    notes = []
    quote_ok = normalize(claim["quote"]) in src
    if not quote_ok:
        notes.append("quote not in article")
    package = claim["package"].strip()
    package_ok = normalize(package) in src
    if not package_ok:
        notes.append("package not in article")

    versions, dropped = [], []
    for v in dict.fromkeys(x.strip() for x in claim["versions"] if x.strip()):
        (versions if has_version(src, v) else dropped).append(v)
    if dropped:
        notes.append(f"versions not in article: {', '.join(dropped)}")
    ids, dropped = [], []
    for i in dict.fromkeys(x.strip().upper() for x in claim["identifiers"] if x.strip()):
        (ids if normalize(i) in src else dropped).append(i)
    if dropped:
        notes.append(f"identifiers not in article: {', '.join(dropped)}")

    return GroundedClaim(claim["ecosystem"], package, tuple(versions), claim["kind"], tuple(ids),
                         claim["quote"].strip(), quote_ok and package_ok, tuple(notes))
