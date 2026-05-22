"""書類本体 cache の Protocol + LocalCache 実装。

書類本体 (PDF / XBRL ZIP) は EDINET 上で immutable なため、 一度取得したら
TTL ∞ で cache してよい。 cache のバックエンドは利用シーンで変えたい
(ローカル開発: ファイル / Cloud Run: GCS) ので Protocol で抽象化する。

GcsCache は Phase 1c で別 PR にて実装予定。
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


__all__ = ["Cache", "ContentType", "InMemoryCache", "LocalCache"]
