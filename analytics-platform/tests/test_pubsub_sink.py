"""PubSubSink / build_sink テスト (google-cloud-pubsub を fake publisher でモック)。"""

from __future__ import annotations

from pathlib import Path

from analytics_platform.gcp_config import (
    PubSubAnalyticsConfig,
    build_sink,
    detect_storage_backend,
    load_pubsub_config,
)
from analytics_platform.observability.sinks.file_sink import RotatingFileSink
from analytics_platform.observability.sinks.pubsub_sink import PubSubSink


class _FakeFuture:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def result(self, timeout: float | None = None) -> str:
        return "msg-id"


class _FakePublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    def topic_path(self, project: str, name: str) -> str:
        return f"projects/{project}/topics/{name}"

    def publish(self, topic: str, data: bytes) -> _FakeFuture:
        self.published.append((topic, data))
        return _FakeFuture(data)


# ----- PubSubSink -----


async def test_pubsub_sink_publishes_each_line() -> None:
    pub = _FakePublisher()
    sink = PubSubSink(topic="analytics-events", project_id="proj", publisher=pub)

    await sink.write_batch(['{"event_id":"1"}', '{"event_id":"2"}'])

    assert len(pub.published) == 2
    assert pub.published[0][0] == "projects/proj/topics/analytics-events"
    assert pub.published[0][1] == b'{"event_id":"1"}'
    assert pub.published[1][1] == b'{"event_id":"2"}'


async def test_pubsub_sink_empty_batch_is_noop() -> None:
    pub = _FakePublisher()
    sink = PubSubSink(topic="t", project_id="p", publisher=pub)

    await sink.write_batch([])

    assert pub.published == []


async def test_pubsub_sink_accepts_full_topic_path() -> None:
    pub = _FakePublisher()
    sink = PubSubSink(topic="projects/p/topics/full", publisher=pub)

    await sink.write_batch(['{"event_id":"x"}'])

    assert pub.published[0][0] == "projects/p/topics/full"


# ----- build_sink / load_pubsub_config -----


def test_build_sink_returns_pubsub_when_configured(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "pubsub")
    monkeypatch.setenv("ANALYTICS_PUBSUB_TOPIC", "analytics-events")
    monkeypatch.setenv("ANALYTICS_GCP_PROJECT", "proj")

    sink = build_sink(local_root=tmp_path, service_name="svc")

    assert isinstance(sink, PubSubSink)


def test_build_sink_with_explicit_pubsub_config_overrides_env(
    monkeypatch, tmp_path: Path
) -> None:
    # env が local でも、明示 config を渡せば PubSubSink になる (.env consumer 向け)。
    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "local")
    cfg = PubSubAnalyticsConfig(topic="analytics-events", project_id="proj")

    sink = build_sink(local_root=tmp_path, service_name="svc", pubsub_config=cfg)

    assert isinstance(sink, PubSubSink)


def test_build_sink_defaults_to_local(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ANALYTICS_STORAGE_BACKEND", raising=False)

    sink = build_sink(local_root=tmp_path, service_name="svc")

    assert isinstance(sink, RotatingFileSink)


def test_build_sink_falls_back_to_local_when_topic_missing(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "pubsub")
    monkeypatch.delenv("ANALYTICS_PUBSUB_TOPIC", raising=False)

    sink = build_sink(local_root=tmp_path, service_name="svc")

    assert isinstance(sink, RotatingFileSink)


def test_load_pubsub_config(monkeypatch) -> None:
    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "pubsub")
    monkeypatch.setenv("ANALYTICS_PUBSUB_TOPIC", "t")
    monkeypatch.setenv("ANALYTICS_GCP_PROJECT", "p")

    cfg = load_pubsub_config()

    assert cfg is not None
    assert cfg.topic == "t"
    assert cfg.project_id == "p"
    assert detect_storage_backend() == "pubsub"


def test_load_pubsub_config_none_when_local(monkeypatch) -> None:
    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "local")

    assert load_pubsub_config() is None
