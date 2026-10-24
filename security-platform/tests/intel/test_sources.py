"""情報源クライアント (HTTP 層) のテスト。httpx.MockTransport で外部通信を置き換える。"""
from __future__ import annotations

import gzip
import io
import json
import zipfile

import httpx
import pytest

from src.common.http import make_client, with_retry
from src.common.raw_store import RawStore
from src.intel.sources.epss import iter_epss, score_date
from src.intel.sources.kev import fetch_kev, parse_kev
from src.intel.sources.osv import (
    OsvClient,
    ecosystem_slug,
    iter_zip_records,
    publish_scanner_db,
)

BASE = "https://osv.test"
MODIFIED = (
    "2026-10-24T01:00:00.900000000Z,PyPI/GHSA-new\n"
    "2026-10-24T01:00:00.100000000Z,GitHub Actions/GHSA-gha\n"
    "2026-10-23T00:00:00Z,PyPI/GHSA-old\n"
)


def zip_bytes(records: dict[str, object]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in records.items():
            zf.writestr(name, body if isinstance(body, str) else json.dumps(body))
    return buf.getvalue()


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.raw_path.decode()
    routes = {
        "/ecosystems.txt": httpx.Response(200, text="PyPI\n[EMPTY]\nGitHub Actions\n\n"),
        "/modified_id.csv": httpx.Response(200, text=MODIFIED),
        "/PyPI/GHSA-new.json": httpx.Response(200, json={"id": "GHSA-new"}),
        "/GitHub%20Actions/all.zip": httpx.Response(
            200, content=zip_bytes({"GHSA-gha.json": {"id": "GHSA-gha"}, "broken.json": "{", "x.txt": "-"})
        ),
    }
    return routes.get(path, httpx.Response(404))


@pytest.fixture
def osv() -> OsvClient:
    return OsvClient(make_client(httpx.MockTransport(handler)), BASE)


def test_list_ecosystems_skips_empty(osv):
    assert osv.list_ecosystems() == ["PyPI", "GitHub Actions"]


def test_modified_since_stops_at_cursor(osv):
    assert osv.latest_modified() == "2026-10-24T01:00:00.900000000Z"
    got = osv.modified_since("2026-10-24T01:00:00.1Z")
    assert [(e.ecosystem, e.record_id) for e in got] == [("PyPI", "GHSA-new"), ("GitHub Actions", "GHSA-gha")]


def test_fetch_record_returns_none_on_404(osv):
    assert osv.fetch_record("PyPI", "GHSA-new") == {"id": "GHSA-new"}
    assert osv.fetch_record("PyPI", "GHSA-gone") is None


def test_download_zip_quotes_ecosystem_and_skips_broken_members(osv, tmp_path):
    store = RawStore(tmp_path / "raw")
    path = osv.download_all_zip("GitHub Actions", store, f"full-r1/{ecosystem_slug('GitHub Actions')}.zip")
    assert path.name == "GitHub_Actions.zip"
    assert [rec["id"] for _, rec in iter_zip_records(path)] == ["GHSA-gha"]
    target = publish_scanner_db(path, tmp_path / "osv-db", "GitHub Actions")
    assert target.read_bytes() == path.read_bytes()
    assert publish_scanner_db(path, tmp_path / "osv-db", "GitHub Actions") == target  # 上書き可能


def test_with_retry_retries_5xx_and_transport_errors_only():
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("down")
        if calls["n"] == 2:
            raise httpx.HTTPStatusError("x", request=httpx.Request("GET", BASE),
                                        response=httpx.Response(503))
        return "ok"

    assert with_retry(flaky, what="t", sleep=lambda _s: None) == "ok"

    def not_found() -> str:
        raise httpx.HTTPStatusError("x", request=httpx.Request("GET", BASE), response=httpx.Response(404))

    with pytest.raises(httpx.HTTPStatusError):
        with_retry(not_found, what="t", sleep=lambda _s: None)


def test_kev_fetch_and_parse():
    body = json.dumps({"vulnerabilities": [{"cveID": "CVE-2026-1", "dateAdded": "2026-10-01"},
                                           {"cveID": ""}]}).encode()
    client = make_client(httpx.MockTransport(lambda _r: httpx.Response(200, content=body)))
    entries = parse_kev(fetch_kev(client, "https://kev.test"))
    assert [(e.cve, e.date_added) for e in entries] == [("CVE-2026-1", "2026-10-01")]


def test_epss_parse_gzip_and_plain():
    text = "#model_version:v2025.03.14,score_date:2026-10-23T00:00:00Z\ncve,epss,percentile\nCVE-1,0.5,0.9\nbad,x,y\n"
    for body in (gzip.compress(text.encode()), text.encode()):
        assert score_date(body) == "2026-10-23T00:00:00Z"
        assert [(s.cve, s.epss) for s in iter_epss(body)] == [("CVE-1", 0.5)]
    assert score_date(b"cve,epss,percentile\n") is None
