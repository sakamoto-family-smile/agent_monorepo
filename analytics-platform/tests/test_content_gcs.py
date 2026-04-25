"""GCSPayloadWriter テスト。"""
from __future__ import annotations

from unittest.mock import MagicMock

from analytics_platform.observability.content import ContentRouter
from analytics_platform.observability.content_gcs import GCSPayloadWriter


class _FakeBlob:
    def __init__(self, name, storage):
        self._name = name
        self._storage = storage
        self.content_type = None

    def upload_from_string(self, content: bytes, content_type=None):
        self._storage[self._name] = content
        self.content_type = content_type


class _FakeBucket:
    def __init__(self, storage):
        self._storage = storage

    def blob(self, key):
        return _FakeBlob(key, self._storage)


class _FakeClient:
    def __init__(self):
        self.storage: dict[str, bytes] = {}

    def bucket(self, _name):
        return _FakeBucket(self.storage)


def test_write_returns_gs_uri_and_uploads() -> None:
    fake = _FakeClient()
    writer = GCSPayloadWriter(
        bucket_name="test-bucket", key_prefix="payloads/", client=fake
    )
    uri = writer.write(
        service_name="svc",
        event_id="eid123",
        content=b"hello world",
        extension="txt",
    )
    assert uri.startswith("gs://test-bucket/payloads/svc/")
    assert uri.endswith("/eid123.txt")
    key = next(iter(fake.storage))
    assert fake.storage[key] == b"hello world"


def test_unknown_extension_defaults_to_bin() -> None:
    fake = _FakeClient()
    writer = GCSPayloadWriter(bucket_name="b", client=fake)
    uri = writer.write(service_name="s", event_id="e", content=b"x", extension="")
    assert uri.endswith(".bin")


def test_prefix_normalization() -> None:
    fake = _FakeClient()
    writer = GCSPayloadWriter(bucket_name="b", key_prefix="", client=fake)
    uri = writer.write(service_name="s", event_id="e", content=b"x", extension="txt")
    # 先頭 prefix 無し (`gs://b/s/yyyy-mm-dd/e.txt` 形式)
    assert uri.startswith("gs://b/s/")


def test_content_router_with_gcs_writer_switches_when_above_threshold() -> None:
    fake = _FakeClient()
    writer = GCSPayloadWriter(bucket_name="b", client=fake)
    router = ContentRouter(writer=writer, inline_threshold_bytes=8)

    small = router.route(service_name="s", event_id="e1", content="short")
    assert small.content_uri is None
    assert small.content_text == "short"

    big = router.route(service_name="s", event_id="e2", content="x" * 100)
    assert big.content_uri is not None
    assert big.content_uri.startswith("gs://b/")
    assert big.content_text is None


def test_upload_failure_bubbles_up() -> None:
    fake_client = MagicMock()
    fake_blob = MagicMock()
    fake_blob.upload_from_string.side_effect = RuntimeError("GCS down")
    fake_bucket = MagicMock()
    fake_bucket.blob.return_value = fake_blob
    fake_client.bucket.return_value = fake_bucket

    writer = GCSPayloadWriter(bucket_name="b", client=fake_client)
    try:
        writer.write(service_name="s", event_id="e", content=b"x", extension="txt")
    except RuntimeError as exc:
        assert "GCS down" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
