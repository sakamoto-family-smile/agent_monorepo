"""書類本体 cache の Protocol + LocalCache / GcsCache / InMemoryCache 実装。

書類本体 (PDF / XBRL ZIP) は EDINET 上で immutable なため、 一度取得したら
TTL ∞ で cache してよい。 cache のバックエンドは利用シーンで変えたい
(ローカル開発: ファイル / Cloud Run: GCS) ので Protocol で抽象化する。

GcsCache は optional dep (`[gcs]` extra で google-cloud-storage を入れる)。
SDK が同期 API のため、 asyncio.to_thread で wrap して非同期化する。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

ContentType = Literal["pdf", "xbrl_zip", "attach_zip"]


@runtime_checkable
class Cache(Protocol):
    """書類本体 cache の抽象。

    実装は LocalCache (Phase 1a) / GcsCache (Phase 1c) を予定。
    """

    async def get(self, document_id: str, content_type: ContentType) -> bytes | None: ...

    async def put(
        self, document_id: str, content_type: ContentType, payload: bytes
    ) -> str: ...
    """`put` は cache uri (gs://... / file://...) を返す。 consumer は DB に保存可能。"""


class LocalCache:
    """ローカルファイルシステム上の cache。

    レイアウト: `<root>/<content_type>/<document_id>.<ext>`
        例: `./data/edinet/pdf/S100ABC1.pdf`
    """

    _EXT_MAP: dict[ContentType, str] = {
        "pdf": ".pdf",
        "xbrl_zip": ".zip",
        "attach_zip": ".zip",
    }

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, document_id: str, content_type: ContentType) -> Path:
        ext = self._EXT_MAP[content_type]
        return self._root / content_type / f"{document_id}{ext}"

    async def get(self, document_id: str, content_type: ContentType) -> bytes | None:
        path = self._path_for(document_id, content_type)
        if not path.exists():
            return None
        return await asyncio.to_thread(path.read_bytes)

    async def put(
        self, document_id: str, content_type: ContentType, payload: bytes
    ) -> str:
        path = self._path_for(document_id, content_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, payload)
        return f"file://{path.resolve()}"


class InMemoryCache:
    """テスト用の in-memory cache。 本番では使わない。"""

    def __init__(self) -> None:
        self._store: dict[tuple[str, ContentType], bytes] = {}

    async def get(self, document_id: str, content_type: ContentType) -> bytes | None:
        return self._store.get((document_id, content_type))

    async def put(
        self, document_id: str, content_type: ContentType, payload: bytes
    ) -> str:
        self._store[(document_id, content_type)] = payload
        return f"memory://{document_id}/{content_type}"


class GcsCache:
    """Google Cloud Storage 上の cache (Cloud Run 用)。

    レイアウト: `gs://<bucket>/<prefix><content_type>/<document_id>.<ext>`
        例: `gs://my-edinet-cache/edinet/pdf/S100ABC1.pdf`

    依存: `google-cloud-storage` (optional dep `[gcs]`)。 lazy import。

    認証: ADC (Application Default Credentials)。 Cloud Run では SA に
    `roles/storage.objectAdmin` (cache bucket に対して) が必要。

    google-cloud-storage SDK は同期 API のため、 `asyncio.to_thread` で
    wrap して Protocol の async 規約に揃える。

    Example:
        cache = GcsCache(
            bucket="my-edinet-cache",
            prefix="edinet/",            # default
            project_id=None,             # ADC で推論
        )
        # consumer 側で DI:
        client = EdinetClient(api_key=..., cache=cache)
    """

    _EXT_MAP: dict[ContentType, str] = {
        "pdf": ".pdf",
        "xbrl_zip": ".zip",
        "attach_zip": ".zip",
    }

    _MIME_MAP: dict[ContentType, str] = {
        "pdf": "application/pdf",
        "xbrl_zip": "application/zip",
        "attach_zip": "application/zip",
    }

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "edinet/",
        project_id: str | None = None,
        client: object | None = None,
    ) -> None:
        """`client` は DI 用 (`storage.Client` 互換)。 None なら ADC で構築。"""
        if not bucket:
            raise ValueError("bucket is required")
        self._bucket_name = bucket
        self._prefix = _normalize_prefix(prefix)
        self._project_id = project_id
        self._client = client  # lazy build if None
        self._bucket = None  # lazy build

    def _ensure_bucket(self) -> object:
        if self._bucket is not None:
            return self._bucket
        if self._client is None:
            try:
                from google.cloud import storage  # noqa: PLC0415
            except ImportError as err:  # pragma: no cover — optional dep 未導入時
                raise ImportError(
                    "GcsCache requires `google-cloud-storage`. "
                    "Install with: `pip install 'edinet-client[gcs]'`"
                ) from err
            self._client = storage.Client(project=self._project_id)
        self._bucket = self._client.bucket(self._bucket_name)  # type: ignore[union-attr]
        return self._bucket

    def _key_for(self, document_id: str, content_type: ContentType) -> str:
        ext = self._EXT_MAP[content_type]
        return f"{self._prefix}{content_type}/{document_id}{ext}"

    async def get(self, document_id: str, content_type: ContentType) -> bytes | None:
        bucket = self._ensure_bucket()
        key = self._key_for(document_id, content_type)
        blob = bucket.blob(key)  # type: ignore[union-attr]

        def _download() -> bytes | None:
            if not blob.exists():
                return None
            return blob.download_as_bytes()

        return await asyncio.to_thread(_download)

    async def put(
        self, document_id: str, content_type: ContentType, payload: bytes
    ) -> str:
        bucket = self._ensure_bucket()
        key = self._key_for(document_id, content_type)
        blob = bucket.blob(key)  # type: ignore[union-attr]
        mime = self._MIME_MAP[content_type]

        await asyncio.to_thread(blob.upload_from_string, payload, content_type=mime)
        return f"gs://{self._bucket_name}/{key}"


def _normalize_prefix(prefix: str) -> str:
    """prefix を `foo/bar/` 形式 (末尾 `/` 付き、 先頭 `/` 無し) に揃える。"""
    p = (prefix or "").strip("/")
    return f"{p}/" if p else ""


__all__ = ["Cache", "ContentType", "GcsCache", "InMemoryCache", "LocalCache"]
