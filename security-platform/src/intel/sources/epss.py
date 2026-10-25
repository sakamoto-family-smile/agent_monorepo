"""FIRST EPSS (日次 CSV.gz、全 CVE 分)。

先頭行は ``#model_version:v2025.03.14,score_date:2026-10-23T12:55:00Z`` 形式のコメント。
"""
from __future__ import annotations

import csv
import gzip
import io
from collections.abc import Iterator

import httpx

from ...common.http import with_retry
from ..signals import EpssScore


def fetch_epss(client: httpx.Client, url: str) -> bytes:
    def go() -> bytes:
        r = client.get(url)
        r.raise_for_status()
        return r.content

    return with_retry(go, what="epss")


def _text(body: bytes) -> io.StringIO:
    raw = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
    return io.StringIO(raw.decode("utf-8"))


def _header(body: bytes, name: str) -> str | None:
    first = _text(body).readline().strip()
    if not first.startswith("#"):
        return None
    for part in first.lstrip("#").split(","):
        key, _, value = part.partition(":")
        if key.strip() == name:
            return value.strip()
    return None


def score_date(body: bytes) -> str | None:
    return _header(body, "score_date")


def model_version(body: bytes) -> str | None:
    """モデルが変わるとほぼ全 CVE のスコアが一斉に動くので、その日は上昇検知をしない。"""
    return _header(body, "model_version")


def iter_epss(body: bytes) -> Iterator[EpssScore]:
    lines = (ln for ln in _text(body) if not ln.startswith("#"))
    for row in csv.DictReader(lines):
        try:
            yield EpssScore(row["cve"].strip(), float(row["epss"]), float(row["percentile"]))
        except (KeyError, ValueError, AttributeError):
            continue
