"""GCS 版 PayloadWriter。

`PayloadWriter` Protocol (`observability.content.PayloadWriter`) の GCS 版。
閾値を超える大きなコンテンツを GCS に直接書き出し、`gs://bucket/key` URI を返す。

依存:
  - `google-cloud-storage` は optional extra (`[gcs]`)。import を遅延。

設計:
  - key 構造は LocalFilePayloadWriter と同じく `{service_name}/{dt}/{event_id}.{ext}`
  - 書き込みは blocking (google-cloud-storage は同期 API)。
    AnalyticsLogger は flush の async コンテキストで呼ばれるが、ContentRouter.route は
    同期関数のため、ここも同期でよい。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass
class GCSPayloadWriter:
    """GCS に大容量 payload を書き出し `gs://bucket/key` を返す。

    使用例:
        writer = GCSPayloadWriter(
            bucket_name="youyaku-ai-analytics",
            key_prefix="payloads/",
            project_id="youyaku-ai",
        )
        router = ContentRouter(writer=writer, inline_threshold_bytes=8192)
    """

    bucket_name: str
    key_prefix: str = "payloads/"
    project_id: str | None = None
    client: object | None = None

    def _normalize_prefix(self) -> str:
        p = (self.key_prefix or "").strip("/")
        return f"{p}/" if p else ""

    def _get_bucket(self):
        if self.client is not None:
            return self.client.bucket(self.bucket_name)
        from google.cloud import storage  # noqa: PLC0415

        client = storage.Client(project=self.project_id)
        return client.bucket(self.bucket_name)

    def write(
        self,
        *,
        service_name: str,
        event_id: str,
        content: bytes,
        extension: str,
    ) -> str:
        dt = datetime.now(UTC).strftime("%Y-%m-%d")
        safe_ext = (extension or "bin").lstrip(".") or "bin"
        key = f"{self._normalize_prefix()}{service_name}/{dt}/{event_id}.{safe_ext}"
        uri = f"gs://{self.bucket_name}/{key}"

        try:
            bucket = self._get_bucket()
            blob = bucket.blob(key)
            content_type = _guess_content_type(safe_ext)
            blob.upload_from_string(content, content_type=content_type)
        except Exception:
            logger.exception("GCS payload upload failed: key=%s size=%d", key, len(content))
            raise

        return uri


def _guess_content_type(ext: str) -> str:
    mapping = {
        "txt": "text/plain; charset=utf-8",
        "json": "application/json",
        "html": "text/html; charset=utf-8",
        "md": "text/markdown",
    }
    return mapping.get(ext.lower(), "application/octet-stream")
