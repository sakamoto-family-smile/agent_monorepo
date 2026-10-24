"""OSV.dev の GCS 公開バケットからの取得。

- 全量: ``<ecosystem>/all.zip`` (エコシステムごと。ブートストラップは途中から再開できる)
- 差分: ルートの ``modified_id.csv`` (新しい順) を先頭から読み、カーソルより古い行で打ち切る。
  変更されたレコードは ``<ecosystem>/<id>.json`` を個別に取る
"""
from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from ...common.http import with_retry
from ...common.raw_store import RawStore
from ...common.timeutil import parse_iso

logger = logging.getLogger(__name__)

EMPTY_ECOSYSTEM = "[EMPTY]"
CHUNK = 1 << 20


@dataclass(frozen=True)
class ModifiedEntry:
    modified: str
    ecosystem: str
    record_id: str


def ecosystem_slug(ecosystem: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "_", ecosystem)


class OsvClient:
    def __init__(self, client: httpx.Client, base_url: str) -> None:
        self._http = client
        self._base = base_url.rstrip("/")

    def _url(self, *parts: str) -> str:
        return "/".join([self._base, *(quote(p) for p in parts)])

    def list_ecosystems(self) -> list[str]:
        def go() -> str:
            r = self._http.get(self._url("ecosystems.txt"))
            r.raise_for_status()
            return r.text

        lines = [ln.strip() for ln in with_retry(go, what="osv ecosystems").splitlines()]
        return [ln for ln in lines if ln and ln != EMPTY_ECOSYSTEM]

    def _iter_modified_lines(self) -> Iterator[ModifiedEntry]:
        with self._http.stream("GET", self._url("modified_id.csv")) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.strip():
                    continue
                ts, _, path = line.strip().partition(",")
                eco, _, rid = path.rpartition("/")
                if eco and rid:
                    yield ModifiedEntry(ts, eco, rid)

    def latest_modified(self) -> str | None:
        """全量取得の直前に呼び、取得後の差分カーソルの起点にする。"""
        return with_retry(
            lambda: next((e.modified for e in self._iter_modified_lines()), None),
            what="osv modified head",
        )

    def modified_since(self, cursor: str) -> list[ModifiedEntry]:
        """カーソル以降 (同時刻を含む) の変更を新しい順に返す。行を読むだけで本文は取らない。"""
        since: datetime = parse_iso(cursor)

        def go() -> list[ModifiedEntry]:
            out: list[ModifiedEntry] = []
            for entry in self._iter_modified_lines():
                if parse_iso(entry.modified) < since:
                    break
                out.append(entry)
            return out

        return with_retry(go, what="osv modified_id.csv")

    def fetch_record(self, ecosystem: str, record_id: str) -> dict[str, Any] | None:
        def go() -> dict[str, Any] | None:
            r = self._http.get(self._url(ecosystem, f"{record_id}.json"))
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()

        return with_retry(go, what=f"osv record {record_id}")

    def download_all_zip(self, ecosystem: str, store: RawStore, name: str) -> Path:
        def go() -> Path:
            with (
                store.open_new("osv", name) as (f, path),
                self._http.stream("GET", self._url(ecosystem, "all.zip")) as r,
            ):
                r.raise_for_status()
                for chunk in r.iter_bytes(CHUNK):
                    f.write(chunk)
            return path

        return with_retry(go, what=f"osv {ecosystem}/all.zip")


def iter_zip_records(path: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """all.zip 内の各 JSON を (メンバー名, レコード) で返す。壊れたメンバーは飛ばす。"""
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.endswith(".json"):
                continue
            try:
                with zf.open(info) as f:
                    yield info.filename, json.load(io.TextIOWrapper(f, encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError, KeyError):
                logger.warning("skip broken member %s in %s", info.filename, path.name)


def publish_scanner_db(zip_path: Path, osv_db_dir: Path, ecosystem: str) -> Path:
    """osv-scanner のオフライン DB 配置 (``osv-scanner/<ecosystem>/all.zip``) に置く。"""
    target = osv_db_dir / "osv-scanner" / ecosystem / "all.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name("all.zip.tmp")
    if tmp.exists():
        tmp.unlink()
    try:
        tmp.hardlink_to(zip_path)
    except OSError:
        tmp.write_bytes(zip_path.read_bytes())
    tmp.replace(target)
    return target
