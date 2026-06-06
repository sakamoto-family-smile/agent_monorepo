"""Pub/Sub シンク: 各行 (JSON イベント) を Pub/Sub topic に publish する。

PROPOSAL-0010 案E-1 の入口。`JsonlSink` Protocol (`write_batch`) を実装し、
`RotatingFileSink` の差し替えとして使える。出口は Cloud Storage サブスクが
raw バケットへ NDJSON を書く (terraform 側、`pubsub.tf`)。

- `google-cloud-pubsub` は optional extra (`[pubsub]`)。**import は遅延**させ、
  ライブラリ本体 / テストは Cloud 無しでも動く。
- publish は `write_batch` 内で `future.result()` まで待つ (= 各 flush 完了時点で
  Pub/Sub に受理済み = durable)。失敗時は例外を投げ、`AnalyticsLogger.flush()` が
  バッファに戻して次回 flush で再送する (組込みリトライ)。
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class PubSubSink:
    """イベント行を Pub/Sub topic へ publish する `JsonlSink` 実装。

    Args:
        topic: topic 短縮名 (例 ``analytics-events``) かフルパス
            (``projects/<p>/topics/<name>``)。
        project_id: 短縮名のとき必須 (未指定なら ADC から推論)。
        publisher: テスト用に注入する PublisherClient 互換オブジェクト。
        publish_timeout: 1 メッセージあたりの publish 待ち秒数。
    """

    def __init__(
        self,
        *,
        topic: str,
        project_id: str | None = None,
        publisher: object | None = None,
        publish_timeout: float = 30.0,
    ) -> None:
        self._topic = topic
        self._project_id = project_id
        self._publisher = publisher
        self._publish_timeout = publish_timeout
        self._topic_path: str | None = None

    def _ensure(self) -> tuple[object, str]:
        if self._publisher is None:
            from google.cloud import pubsub_v1  # noqa: PLC0415

            self._publisher = pubsub_v1.PublisherClient()

        if self._topic_path is None:
            if self._topic.startswith("projects/"):
                self._topic_path = self._topic
            else:
                project = self._project_id
                if not project:
                    import google.auth  # noqa: PLC0415

                    _, project = google.auth.default()
                if not project:
                    raise RuntimeError(
                        "PubSubSink: project を解決できません。"
                        "ANALYTICS_GCP_PROJECT を設定するか topic をフルパスで指定してください。"
                    )
                self._topic_path = self._publisher.topic_path(project, self._topic)

        return self._publisher, self._topic_path

    async def write_batch(self, lines: list[str]) -> None:
        if not lines:
            return

        def _publish() -> None:
            publisher, topic_path = self._ensure()
            futures = [
                publisher.publish(topic_path, line.encode("utf-8")) for line in lines
            ]
            # 受理 (ack) まで待つ = この flush 完了時点で durable。
            for future in futures:
                future.result(timeout=self._publish_timeout)

        # publish/result はブロッキングなのでイベントループを塞がないよう別スレッドで。
        await asyncio.to_thread(_publish)
