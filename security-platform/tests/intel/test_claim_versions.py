"""記事の版の書き方 → 個別の版と range (src/intel/claim_versions.py) のテスト。"""
from __future__ import annotations

import pytest

from src.intel.claim_versions import affects, parse


def events(*pairs: tuple[str, str]) -> dict:
    return {"type": "ECOSYSTEM", "events": [{k: v} for k, v in pairs]}


@pytest.mark.parametrize(("text", "expected"), [
    ("earlier than 1.84.1", events(("introduced", "0"), ("fixed", "1.84.1"))),
    ("grpcio earlier than 1.84.1", None),  # 名前込みの書き方は解釈しない
    ("< 2.0.3", events(("introduced", "0"), ("fixed", "2.0.3"))),
    ("Versions prior to v3.1.0", events(("introduced", "0"), ("fixed", "3.1.0"))),
    ("<= 1.4", events(("introduced", "0"), ("last_affected", "1.4"))),
    ("1.4.2 and earlier", events(("introduced", "0"), ("last_affected", "1.4.2"))),
    (">= 1.2.0, < 1.2.5", events(("introduced", "1.2.0"), ("fixed", "1.2.5"))),
    ("1.2.0 - 1.2.5", events(("introduced", "1.2.0"), ("last_affected", "1.2.5"))),
    ("from 2.0 through 2.3", events(("introduced", "2.0"), ("last_affected", "2.3"))),
    ("3.0.0 and later", events(("introduced", "3.0.0"),)),
    ("version suffix earlier than -2.9.2", None),
])
def test_ranges(text, expected):
    p = parse("PyPI", [text])
    assert p.exact == ()
    assert p.ranges == (() if expected is None else (expected,))
    assert p.unparsed == (() if expected is not None else (text,))


def test_exact_and_dedupe():
    p = parse("npm", ["1.2.3", "v1.2.3", "=1.2.4", "< 2.0.0", "<2.0.0", "latest"])
    assert p.exact == ("1.2.3", "1.2.4")
    assert p.ranges == (events(("introduced", "0"), ("fixed", "2.0.0")),)
    assert p.unparsed == ("latest",)
    assert parse("Go", ["v1.2.3"]).exact == ("v1.2.3",)  # Go は v 付きが正


def test_affects():
    assert affects("PyPI", "1.80.0", ["earlier than 1.84.1"])
    assert not affects("PyPI", "1.84.1", ["earlier than 1.84.1"])
    assert affects("npm", "1.2.3", ["1.2.3"]) and not affects("npm", "1.2.4", ["1.2.3"])
    assert not affects("PyPI", "1.0", [])
    assert not affects("PyPI", "1.0", ["all versions of the old line"])
