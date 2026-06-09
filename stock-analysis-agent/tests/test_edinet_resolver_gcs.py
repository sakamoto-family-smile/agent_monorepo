"""EDINET code resolver の GCS 読み込み (PROPOSAL-0011 P3-B) の unit テスト。"""

from __future__ import annotations

import config
from agents import edinet_collector


class _FakeBlob:
    def download_as_bytes(self):
        return b"csv-bytes"


class _FakeBucket:
    def blob(self, name):
        assert name == "Edinetcode.csv"
        return _FakeBlob()


class _FakeClient:
    def bucket(self, name):
        assert name == "my-bkt"
        return _FakeBucket()


def test_build_resolver_reads_from_gcs(monkeypatch):
    monkeypatch.setattr(
        config.settings, "edinet_code_csv_path", "gs://my-bkt/Edinetcode.csv"
    )
    from google.cloud import storage

    monkeypatch.setattr(storage, "Client", _FakeClient)

    captured = {}

    def _fake_from_bytes(cls, data):
        captured["data"] = data
        return "RESOLVER"

    monkeypatch.setattr(
        edinet_collector.EdinetCodeResolver,
        "from_csv_bytes",
        classmethod(_fake_from_bytes),
    )
    resolver = edinet_collector._build_resolver()
    assert resolver == "RESOLVER"
    assert captured["data"] == b"csv-bytes"


def test_build_resolver_none_when_unset(monkeypatch):
    monkeypatch.setattr(config.settings, "edinet_code_csv_path", "")
    assert edinet_collector._build_resolver() is None


def test_read_gcs_bytes_invalid_uri(monkeypatch):
    assert edinet_collector._read_gcs_bytes("gs://only-bucket") is None
