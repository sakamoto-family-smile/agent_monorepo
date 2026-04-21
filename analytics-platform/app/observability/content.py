"""大きなコンテンツを inline / URI 参照に振り分けるユーティリティ (設計書 §8)。

閾値以下: `content_text` に直接埋込 + `content_hash` を付与
閾値超過: 外部ストレージに保存し `content_uri` を付与 (ローカルは `file://`、GCP 移行時は
          同じ関数シグネチャで GCS アップローダに差し替える)

ローカルの URI は `file://{payloads_dir}/{service}/{dt}/{event_id}.{ext}` の絶対パス。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .hashing import sha256_prefixed

# ---------------------------------------------------------------------------
# 抽象: Payload Writer (ローカル = ファイル、本番 = GCS に差し替え可能)
# ---------------------------------------------------------------------------


class PayloadWriter(Protocol):
    def write(
        self,
        *,
        service_name: str,
        event_id: str,
        content: bytes,
        extension: str,
    ) -> str:
        """content を保存して参照 URI (`file://` / `gs://`) を返す。"""


@dataclass
class LocalFilePayloadWriter:
    """`./data/payloads/{service}/{dt}/{event_id}.{ext}` に書き出し `file://...` を返す。"""

    root_dir: Path

    def write(
        self,
        *,
        service_name: str,
        event_id: str,
        content: bytes,
        extension: str,
    ) -> str:
        dt = datetime.now(UTC).strftime("%Y-%m-%d")
        dir_path = self.root_dir / service_name / dt
        dir_path.mkdir(parents=True, exist_ok=True)
        safe_ext = extension.lstrip(".") or "bin"
        path = dir_path / f"{event_id}.{safe_ext}"
        path.write_bytes(content)
        return f"file://{path.resolve()}"


# ---------------------------------------------------------------------------
# 振り分け結果
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredContent:
    content_text: str | None
    content_uri: str | None
    content_hash: str
    content_size_bytes: int
    content_truncated: bool
    content_preview: str
    content_mime_type: str

    def to_fields(self, *, extra: dict[str, object] | None = None) -> dict[str, object]:
        """MessageEvent 等の `content_*` フィールドにそのまま展開できる dict。"""
        data: dict[str, object] = {
            "content_text": self.content_text,
            "content_uri": self.content_uri,
            "content_hash": self.content_hash,
            "content_size_bytes": self.content_size_bytes,
            "content_truncated": self.content_truncated,
            "content_preview": self.content_preview,
            "content_mime_type": self.content_mime_type,
        }
        if extra:
            data.update(extra)
        return data


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------


@dataclass
class ContentRouter:
    """閾値でコンテンツの格納方法を決めるルータ。

    `content_text` と `content_uri` は排他。
    preview は常に先頭 `preview_chars` 文字を保持する (設計書 §6.2)。
    """

    writer: PayloadWriter
    inline_threshold_bytes: int = 8192
    preview_chars: int = 500
    default_mime_type: str = "text/plain"

    # 閾値を跨いだ場合の truncation 閾値の上限。inline 時は false 固定。
    # URI 送付時は本体を inline に残さないので truncated=true と明示する。
    _truncated_on_uri: bool = field(default=True, init=False)

    def route(
        self,
        *,
        service_name: str,
        event_id: str,
        content: str,
        mime_type: str | None = None,
        extension: str = "txt",
    ) -> StoredContent:
        encoded = content.encode("utf-8")
        size = len(encoded)
        digest = sha256_prefixed(encoded)
        preview = content[: self.preview_chars]
        mime = mime_type or self.default_mime_type

        if size <= self.inline_threshold_bytes:
            return StoredContent(
                content_text=content,
                content_uri=None,
                content_hash=digest,
                content_size_bytes=size,
                content_truncated=False,
                content_preview=preview,
                content_mime_type=mime,
            )

        uri = self.writer.write(
            service_name=service_name,
            event_id=event_id,
            content=encoded,
            extension=extension,
        )
        return StoredContent(
            content_text=None,
            content_uri=uri,
            content_hash=digest,
            content_size_bytes=size,
            content_truncated=self._truncated_on_uri,
            content_preview=preview,
            content_mime_type=mime,
        )
