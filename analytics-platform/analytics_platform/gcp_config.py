"""GCP 連携設定 (env 駆動)。

consumer エージェント (tech-news-agent / piyolog-analytics 等) が明示的に環境変数を
渡さなくても、以下の env があれば GCS 出力に自動的に切り替わるようにするヘルパ。

環境変数:
  ANALYTICS_STORAGE_BACKEND   — "local" (既定) | "gcs"
  ANALYTICS_GCS_BUCKET        — バケット名 (gcs backend 時は必須)
  ANALYTICS_GCS_RAW_PREFIX    — raw JSONL の prefix (既定 "uploaded/")
  ANALYTICS_GCS_PAYLOAD_PREFIX— 大容量 payload の prefix (既定 "payloads/")
  ANALYTICS_GCP_PROJECT       — GCP プロジェクト ID (明示しないと ADC から推論)

Cloud Run / Workload Identity 前提: project は省略可。ローカルから試す場合は
`gcloud auth application-default login` + `ANALYTICS_GCP_PROJECT=youyaku-ai` を設定する。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GcsAnalyticsConfig:
    bucket_name: str
    raw_prefix: str
    payload_prefix: str
    project_id: str | None


def detect_storage_backend() -> str:
    """"local" | "gcs"。`ANALYTICS_STORAGE_BACKEND` で切替。"""
    return (os.environ.get("ANALYTICS_STORAGE_BACKEND") or "local").lower()


def load_gcs_config() -> GcsAnalyticsConfig | None:
    """env から GCS 設定を読み込む。backend が gcs でない / bucket 未設定なら None。"""
    backend = detect_storage_backend()
    if backend != "gcs":
        return None
    bucket = os.environ.get("ANALYTICS_GCS_BUCKET", "").strip()
    if not bucket:
        logger.warning(
            "ANALYTICS_STORAGE_BACKEND=gcs but ANALYTICS_GCS_BUCKET not set; "
            "falling back to local backend"
        )
        return None
    return GcsAnalyticsConfig(
        bucket_name=bucket,
        raw_prefix=os.environ.get("ANALYTICS_GCS_RAW_PREFIX", "uploaded/"),
        payload_prefix=os.environ.get("ANALYTICS_GCS_PAYLOAD_PREFIX", "payloads/"),
        project_id=(os.environ.get("ANALYTICS_GCP_PROJECT") or None),
    )


def build_payload_writer(*, local_root: Path):
    """`ContentRouter` に渡す `PayloadWriter` を env に従って構築。

    - backend=gcs + bucket 設定あり → `GCSPayloadWriter`
    - それ以外 → `LocalFilePayloadWriter`
    """
    # 遅延 import で google-cloud-storage への hard 依存を避ける
    cfg = load_gcs_config()
    if cfg is None:
        from .observability.content import LocalFilePayloadWriter  # noqa: PLC0415

        return LocalFilePayloadWriter(root_dir=local_root)

    from .observability.content_gcs import GCSPayloadWriter  # noqa: PLC0415

    return GCSPayloadWriter(
        bucket_name=cfg.bucket_name,
        key_prefix=cfg.payload_prefix,
        project_id=cfg.project_id,
    )


def build_upload_transport(*, raw_root: Path):
    """`LocalUploader` に渡す `UploadTransport` を env に従って構築。

    - backend=gcs + bucket 設定あり → `GCSTransport`
    - それ以外 → `LocalMoveTransport`
    """
    cfg = load_gcs_config()
    if cfg is None:
        from .uploader.local_uploader import LocalMoveTransport  # noqa: PLC0415

        return LocalMoveTransport(raw_root=raw_root)

    from .uploader.gcs_transport import GCSTransport  # noqa: PLC0415

    return GCSTransport(
        raw_root=raw_root,
        bucket_name=cfg.bucket_name,
        dest_prefix=cfg.raw_prefix,
        project_id=cfg.project_id,
    )
