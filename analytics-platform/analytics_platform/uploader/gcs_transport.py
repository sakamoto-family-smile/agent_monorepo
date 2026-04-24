"""GCS への Upload Transport 実装。

`UploadTransport` Protocol (`local_uploader.UploadTransport`) の GCS 版。
`LocalUploader` にそのまま渡せば、raw ファイルを GCS にアップロードし、
成功後にローカルから削除する (raw → uploaded 相当)。

依存:
  - `google-cloud-storage` は optional extra (`[gcs]`)。import を遅延させて
    analytics-platform を GCP 無しでも使える状態を維持する。

設計:
  - `bucket_name` は必須。`dest_prefix` は省略可 (既定 `uploaded/`)。
  - src の Hive partition 構造 (`service_name=.../event_type=.../dt=.../hour=.../*.jsonl[.gz]`)
    を保って GCS key にマップする。
  - アップロード成功後 src を削除 (LocalMoveTransport の「移動」セマンティクスに合わせる)。
  - 失敗時は例外を上に投げる。`LocalUploader._try_upload` が tenacity でリトライし、
    最大試行を超えると `dead_letter/` に移動する既存仕組みに委譲する。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class GCSTransport:
    """GCS に JSONL ファイル 1 本ずつアップロードする Transport。

    使用例:
        transport = GCSTransport(
            raw_root=Path("./data/raw"),
            bucket_name="youyaku-ai-analytics",
            dest_prefix="uploaded/",
            project_id="youyaku-ai",
        )
        uploader = LocalUploader(
            raw_root=..., uploaded_root=Path("/tmp/noop_uploaded"),
            dead_letter_root=..., transport=transport,
        )
        await uploader.run_once()
    """

    raw_root: Path
    bucket_name: str
    dest_prefix: str = "uploaded/"
    project_id: str | None = None
    content_type_default: str = "application/x-ndjson"
    # 直接テストで注入したい時用 (google-cloud-storage Client 互換)
    client: object | None = None

    def _normalize_prefix(self) -> str:
        p = (self.dest_prefix or "").strip("/")
        return f"{p}/" if p else ""

    def _build_key(self, src: Path) -> str:
        rel = src.relative_to(self.raw_root).as_posix()
        return f"{self._normalize_prefix()}{rel}"

    def _get_bucket(self):
        if self.client is not None:
            return self.client.bucket(self.bucket_name)
        from google.cloud import storage  # noqa: PLC0415

        client = storage.Client(project=self.project_id)
        return client.bucket(self.bucket_name)

    async def send(self, src: Path, *, dest_root: Path) -> str:
        """GCS にアップロードし、成功後 src を削除して `gs://.../key` を文字列で返す。

        `dest_root` 引数は `UploadTransport` Protocol との互換のため受け取るが、
        GCS ではローカルの `dest_root` は使わない。代わりに `bucket_name` /
        `dest_prefix` を使う。戻り値を `Path` ではなく `str` にしているのは、
        Python の `Path` が `gs://` の二重スラッシュを 1 つに折り畳むため
        (`gs:/bucket/key` になる)。`UploadTransport` Protocol は `str | Path` を
        許容するよう緩めてある。
        """
        key = self._build_key(src)
        blob_uri = f"gs://{self.bucket_name}/{key}"

        def _upload() -> None:
            bucket = self._get_bucket()
            blob = bucket.blob(key)
            content_type = (
                "application/gzip" if src.suffix == ".gz" else self.content_type_default
            )
            blob.upload_from_filename(str(src), content_type=content_type)

        try:
            await asyncio.to_thread(_upload)
        except Exception:
            logger.exception("GCS upload failed: src=%s key=%s", src, key)
            raise

        # 成功したらローカルから削除
        try:
            await asyncio.to_thread(src.unlink)
        except Exception:
            logger.warning("GCS upload ok but local unlink failed: %s", src, exc_info=True)

        logger.info("GCS upload ok: %s → %s", src, blob_uri)
        return blob_uri
