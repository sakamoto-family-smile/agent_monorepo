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
    """全文 Markdown を保存して配信 URL を返す (DL 用 attachment)。

    charset=utf-8 を明示しないと LINE 内蔵ブラウザが文字コードを誤判定して
    日本語が文字化けする (実機で確認)。
    """
    if not text:
        return None
    return _store(
        text.encode("utf-8"),
        content_type="text/markdown; charset=utf-8",
        kind="report",
        ext="md",
    )


def store_report_html(text: str) -> str | None:
    """全文 Markdown を HTML 化して保存し、閲覧用 URL を返す。

    LINE 内蔵ブラウザでそのまま読める mobile 向けページ (UTF-8 明示・
    viewport・表/見出しの軽い整形)。DL 用の生 .md は store_report_md が担う。
    """
    if not text:
        return None
    html = _render_report_html(text)
    return _store(
        html.encode("utf-8"),
        content_type="text/html; charset=utf-8",
        kind="report",
        ext="html",
    )


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>分析レポート</title>
<style>
  body {{ font-family: -apple-system, "Hiragino Sans", "Noto Sans JP", sans-serif;
         line-height: 1.7; margin: 0; padding: 16px; color: #1f2937;
         background: #ffffff; font-size: 16px; }}
  h1, h2, h3 {{ line-height: 1.4; margin: 1.2em 0 0.5em; }}
  h1 {{ font-size: 1.3em; border-bottom: 2px solid #1E40AF; padding-bottom: 6px; }}
  h2 {{ font-size: 1.15em; border-left: 4px solid #1E40AF; padding-left: 8px; }}
  h3 {{ font-size: 1.05em; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.85em;
           display: block; overflow-x: auto; }}
  th, td {{ border: 1px solid #d1d5db; padding: 6px 8px; white-space: nowrap; }}
  th {{ background: #eff6ff; }}
  code {{ background: #f3f4f6; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }}
  pre {{ background: #f3f4f6; padding: 10px; border-radius: 6px; overflow-x: auto; }}
  blockquote {{ border-left: 3px solid #9ca3af; margin: 0.5em 0; padding-left: 10px;
               color: #6b7280; }}
  footer {{ margin-top: 2em; padding-top: 1em; border-top: 1px solid #e5e7eb;
           font-size: 0.8em; color: #9ca3af; }}
</style>
</head>
<body>
{body}
<footer>※ 情報提供のみを目的としており、投資勧誘・個別の助言ではありません。</footer>
</body>
</html>
"""


def _render_report_html(md_text: str) -> str:
    """Markdown を HTML 本文に変換してテンプレートに埋める。

    変換失敗時 (markdown 未導入等) は <pre> でプレーン表示にフォールバック。
    """
    try:
        import markdown as md  # noqa: PLC0415

        body = md.markdown(md_text, extensions=["tables", "fenced_code", "nl2br"])
    except Exception:
        logger.exception("markdown→HTML 変換失敗; <pre> にフォールバック")
        import html as _html  # noqa: PLC0415

        body = f"<pre style='white-space:pre-wrap'>{_html.escape(md_text)}</pre>"
    return _HTML_TEMPLATE.format(body=body)


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
        # .md のみ DL (attachment)。HTML はブラウザでそのまま表示する (inline)。
        if ext == "md":
            blob.content_disposition = f'attachment; filename="{blob_name.split("/")[-1]}"'
        blob.upload_from_string(data, content_type=content_type)
    except Exception:
        logger.exception("GCS media upload failed (bucket=%s)", bucket_name)
        return None
    base = config.settings.media_gcs_public_base
    return f"{base}/{bucket_name}/{blob_name}"


__all__ = ["store_chart_png", "store_report_md", "store_report_html"]
