"""チャート画像 / 全文 Markdown の配信先を抽象化する (PROPOSAL-0011 P3-A)。

backend:
  - memory (既定): プロセス内 BlobStore + `public_base_url` でアプリ自身が配信
    (`/api/line/image/{id}.png` / `/api/line/report/{id}.md`)。単一 instance 用。
  - gcs: GCS にアップロードして公開 URL を返す。worker が複数 instance に増えても
    LINE が確実に取得できる (P3-A: Cloud Tasks worker は並列 = 複数 instance)。

返り値は LINE にそのまま渡せる **完全な HTTPS URL**。未設定/失敗時は None
(呼び出し側は media なしで要約のみ配信)。
"""

from __future__ import annotations

import logging
import secrets

import config

logger = logging.getLogger(__name__)


def store_chart_png(data: bytes) -> str | None:
    """チャート PNG を保存して配信 URL を返す。"""
    return _store(data, content_type="image/png", kind="image", ext="png")


def store_report_md(text: str) -> str | None:
    """全文 Markdown を保存して配信 URL を返す (DL 用 attachment)。"""
    if not text:
        return None
    return _store(
        text.encode("utf-8"), content_type="text/markdown", kind="report", ext="md"
    )


def _store(data: bytes, *, content_type: str, kind: str, ext: str) -> str | None:
    backend = config.settings.media_backend
    if backend == "gcs":
        return _store_gcs(data, content_type=content_type, kind=kind, ext=ext)
    return _store_memory(data, content_type=content_type, kind=kind, ext=ext)


# ---------------------------------------------------------------------------
# memory backend (アプリ自身が配信)
# ---------------------------------------------------------------------------


def _store_memory(data: bytes, *, content_type: str, kind: str, ext: str) -> str | None:
    base = config.settings.public_base_url
    if not base:
        return None
    from services.blob_store import get_image_store, get_report_store

    store = get_image_store() if kind == "image" else get_report_store()
    blob_id = store.put(data, content_type)
    return f"{base}/api/line/{kind}/{blob_id}.{ext}"


# ---------------------------------------------------------------------------
# gcs backend (公開バケットにアップロード)
# ---------------------------------------------------------------------------


def _store_gcs(data: bytes, *, content_type: str, kind: str, ext: str) -> str | None:
    bucket_name = config.settings.media_gcs_bucket
    if not bucket_name:
        logger.warning("MEDIA_BACKEND=gcs だが MEDIA_GCS_BUCKET 未設定; media をskip")
        return None
    try:
        from google.cloud import storage  # noqa: PLC0415
    except ImportError:
        logger.warning("google-cloud-storage 未導入; media をskip")
        return None

    blob_name = f"{kind}/{secrets.token_urlsafe(16)}.{ext}"
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        if kind == "report":
            blob.content_disposition = f'attachment; filename="{blob_name.split("/")[-1]}"'
        blob.upload_from_string(data, content_type=content_type)
    except Exception:
        logger.exception("GCS media upload failed (bucket=%s)", bucket_name)
        return None
    base = config.settings.media_gcs_public_base
    return f"{base}/{bucket_name}/{blob_name}"


__all__ = ["store_chart_png", "store_report_md"]
