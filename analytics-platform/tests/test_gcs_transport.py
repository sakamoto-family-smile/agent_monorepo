"""GCSTransport テスト (google-cloud-storage の Client / Bucket / Blob をモック)。"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from analytics_platform.observability.sinks.file_sink import RotatingFileSink
from analytics_platform.uploader.gcs_transport import GCSTransport
from analytics_platform.uploader.local_uploader import LocalUploader


class _FakeBlob:
    def __init__(self, name: str, storage: dict[str, bytes]):
        self._name = name
        self._storage = storage
        self.upload_from_filename_called_with: tuple | None = None

    def upload_from_filename(self, path: str, content_type: str | None = None) -> None:
        with open(path, "rb") as f:
            self._storage[self._name] = f.read()
        self.upload_from_filename_called_with = (path, content_type)


class _FakeBucket:
    def __init__(self, name: str, storage: dict[str, bytes]):
        self.name = name
        self._storage = storage

    def blob(self, key: str) -> _FakeBlob:
        return _FakeBlob(key, self._storage)


class _FakeClient:
    """google.cloud.storage.Client 互換の最小 Fake。"""

    def __init__(self):
        self.storage: dict[str, bytes] = {}
        self._buckets: dict[str, _FakeBucket] = {}

    def bucket(self, bucket_name: str) -> _FakeBucket:
        if bucket_name not in self._buckets:
            self._buckets[bucket_name] = _FakeBucket(bucket_name, self.storage)
        return self._buckets[bucket_name]


async def _seed_raw(tmp_path: Path, n: int = 2) -> None:
    sink = RotatingFileSink(root_dir=tmp_path / "raw", service_name="svc")
    ts = datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    await sink.write_batch(
        [
            '{"event_id":"'
            + str(i)
            + '","event_type":"llm_call","event_timestamp":"'
            + ts.isoformat()
            + '"}'
            for i in range(n)
        ]
    )


# ---------------------------------------------------------------------------
# 直接 GCSTransport.send を叩く
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_uploads_to_gcs_and_removes_local(tmp_path: Path) -> None:
    await _seed_raw(tmp_path, n=1)
    raw_root = tmp_path / "raw"
    src = next(raw_root.rglob("*.jsonl"))

    fake = _FakeClient()
    transport = GCSTransport(
        raw_root=raw_root,
        bucket_name="test-bucket",
        dest_prefix="uploaded/",
        project_id="proj",
        client=fake,
    )
    result = await transport.send(src, dest_root=tmp_path / "uploaded")

    # 戻り値は gs:// URI (str)
    assert isinstance(result, str)
    assert result.startswith("gs://test-bucket/uploaded/")
    # ローカルは削除される
    assert not src.exists()
    # GCS 側にはアップロードされている
    assert len(fake.storage) == 1
    key = next(iter(fake.storage))
    assert key.startswith("uploaded/")
    # Hive partition 構造が保たれている
    assert "service_name=svc" in key
    assert "event_type=llm_call" in key


@pytest.mark.asyncio
async def test_dest_prefix_without_trailing_slash_is_normalized(tmp_path: Path) -> None:
    await _seed_raw(tmp_path, n=1)
    raw_root = tmp_path / "raw"
    src = next(raw_root.rglob("*.jsonl"))
    fake = _FakeClient()
    transport = GCSTransport(
        raw_root=raw_root,
        bucket_name="b",
        dest_prefix="myroot",  # no slash
        client=fake,
    )
    result = await transport.send(src, dest_root=tmp_path / "ignored")
    assert result.startswith("gs://b/myroot/")
    key = next(iter(fake.storage))
    assert key.startswith("myroot/")


@pytest.mark.asyncio
async def test_empty_prefix_allowed(tmp_path: Path) -> None:
    await _seed_raw(tmp_path, n=1)
    raw_root = tmp_path / "raw"
    src = next(raw_root.rglob("*.jsonl"))
    fake = _FakeClient()
    transport = GCSTransport(
        raw_root=raw_root, bucket_name="b", dest_prefix="", client=fake
    )
    await transport.send(src, dest_root=tmp_path / "ignored")
    key = next(iter(fake.storage))
    assert key.startswith("service_name=svc/")


@pytest.mark.asyncio
async def test_upload_failure_raises_and_keeps_local(tmp_path: Path) -> None:
    await _seed_raw(tmp_path, n=1)
    raw_root = tmp_path / "raw"
    src = next(raw_root.rglob("*.jsonl"))

    fake = MagicMock()
    mock_blob = MagicMock()
    mock_blob.upload_from_filename.side_effect = RuntimeError("boom")
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    fake.bucket.return_value = mock_bucket

    transport = GCSTransport(
        raw_root=raw_root, bucket_name="b", client=fake
    )
    with pytest.raises(RuntimeError):
        await transport.send(src, dest_root=tmp_path / "ignored")

    # 失敗時はローカルを削除しない (リトライで再送可能)
    assert src.exists()


# ---------------------------------------------------------------------------
# LocalUploader と組み合わせて run_once ループに載る
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_uploader_with_gcs_transport_end_to_end(tmp_path: Path) -> None:
    await _seed_raw(tmp_path, n=2)
    raw_root = tmp_path / "raw"

    fake = _FakeClient()
    transport = GCSTransport(
        raw_root=raw_root,
        bucket_name="test-bucket",
        client=fake,
    )
    uploader = LocalUploader(
        raw_root=raw_root,
        uploaded_root=tmp_path / "uploaded_not_used",  # GCS 時は未使用
        dead_letter_root=tmp_path / "dead",
        transport=transport,
    )
    outcome = await uploader.run_once()

    assert outcome.dead_letter == []
    assert len(outcome.uploaded) == 1
    # raw はもう空
    assert not list(raw_root.rglob("*.jsonl"))
    # GCS 側に入っている
    assert len(fake.storage) == 1


# ---------------------------------------------------------------------------
# .gz サフィックスの content-type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gzipped_jsonl_uses_gzip_content_type(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    sub = raw_root / "service_name=svc" / "event_type=llm_call" / "dt=2026-04-20" / "hour=10"
    sub.mkdir(parents=True)
    src = sub / "chunk.jsonl.gz"
    src.write_bytes(b"\x1f\x8bfake gzipped")

    fake = MagicMock()
    recorded = {}

    def _upload(path, content_type=None):
        recorded["content_type"] = content_type

    mock_blob = MagicMock()
    mock_blob.upload_from_filename = _upload
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    fake.bucket.return_value = mock_bucket

    transport = GCSTransport(raw_root=raw_root, bucket_name="b", client=fake)
    await transport.send(src, dest_root=tmp_path / "ignored")
    assert recorded["content_type"] == "application/gzip"
