"""PDF アーカイブストレージ (proposal 0003 §4.5 / line 204)。

藤沢市 HP は予告なく PDF を差し替え / 削除する (調査ノート §A2-2 で実例あり)。
ETL Job が PDF を fetch したタイミングで **オリジナルバイトをそのまま保存** しておくことで:

  - データ出典 (citation) の遡及検証
  - URL 切れ後の再パース
  - Wayback バックフィルの代替手段 (Wayback も rate limit / 削除リスクあり)

本モジュールは 3 実装を提供する:

| 実装 | 用途 |
|---|---|
| `GcsArchive` | 本番 (Cloud Storage `fujisawa-pdf-archive` バケット) |
| `LocalArchive` | ローカル開発 / dry-run smoke / テスト |
| `NullArchive` | アーカイブ無効化 (Phase 0 で段階導入する際の OFF スイッチ) |

ETL Job (biyearly_admission / monthly_vacancy / yearly_navi / wayback_backfill) は
PDF を fetch した直後に `archive.put(path, content, ...)` を呼ぶ。
`archive_path()` 関数が `{job}/{year}/{round}/{sha256[:16]}-{filename}` 形式の
決定的なパスを返す (同じ URL は常に同じパスに保存される)。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import urlparse

if TYPE_CHECKING:  # pragma: no cover
    from google.cloud import storage as gcs_storage

_INVALID_FILENAME_CHARS = re.compile(r"[^\w.\-]+")


@dataclass(frozen=True)
class ArchivePut:
    """`PdfArchive.put` の結果 (どこに保存したかを caller に返す)。"""

    backend: str  # 'gcs' / 'local' / 'null'
    path: str  # bucket 内の相対パスや local root からの相対パス


@runtime_checkable
class PdfArchive(Protocol):
    """PDF バイトの永続化先 (本番 GCS / ローカルファイル / no-op)。"""

    async def put(
        self,
        *,
        path: str,
        content: bytes,
        source_url: str,
        fetched_at: datetime,
    ) -> ArchivePut: ...

    async def get(self, path: str) -> bytes: ...

    async def exists(self, path: str) -> bool: ...


def archive_path(
    *,
    job_name: str,
    url: str,
    year: int,
    round: str | None = None,
) -> str:
    """URL から決定的なアーカイブパスを生成。

    フォーマット: `{job_name}/{year}/[{round}/]{sha256[:16]}-{filename}.pdf`

    - 同じ URL は常に同じパス (再 run で重複アップロードを避けるため)
    - filename に query string は含めない
    - 拡張子が無い URL は `.pdf` を追加
    - 危険な文字 (空白 / `?` 等) はハイフンに置換
    """
    parsed = urlparse(url)
    raw_name = parsed.path.rsplit("/", 1)[-1] if parsed.path else ""
    if not raw_name:
        raw_name = "unnamed.pdf"
    filename = _sanitize_filename(raw_name)
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf" if filename else "unnamed.pdf"

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    parts: list[str] = [job_name, str(year)]
    if round:
        parts.append(round)
    parts.append(f"{digest}-{filename}")
    return "/".join(parts)


# ─────────────────────────────────────────────────────────────────────
# LocalArchive (テスト / 開発用)
# ─────────────────────────────────────────────────────────────────────


class LocalArchive:
    """ローカルファイルシステムベースの PdfArchive 実装。

    ETL の手動 smoke / Cloud Run Job デプロイ前検証で使う。
    root 以下に `{path}` の階層を作って書き込む。
    """

    def __init__(self, *, root: Path) -> None:
        self._root = root.resolve()

    async def put(
        self,
        *,
        path: str,
        content: bytes,
        source_url: str,
        fetched_at: datetime,
    ) -> ArchivePut:
        target = self._resolve_inside_root(path)
        await asyncio.to_thread(self._write, target, content)
        return ArchivePut(backend="local", path=path)

    async def get(self, path: str) -> bytes:
        target = self._resolve_inside_root(path)
        if not target.exists():
            raise FileNotFoundError(path)
        return await asyncio.to_thread(target.read_bytes)

    async def exists(self, path: str) -> bool:
        target = self._resolve_inside_root(path)
        return await asyncio.to_thread(target.exists)

    def _resolve_inside_root(self, path: str) -> Path:
        """`{root}/{path}` を絶対パス化しつつ、root 外への traversal を拒否。"""
        target = (self._root / path).resolve()
        try:
            target.relative_to(self._root)
        except ValueError as err:
            raise ValueError(f"path traversal blocked: {path}") from err
        return target

    @staticmethod
    def _write(target: Path, content: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


# ─────────────────────────────────────────────────────────────────────
# NullArchive (OFF スイッチ用)
# ─────────────────────────────────────────────────────────────────────


class NullArchive:
    """no-op の PdfArchive。Phase 0 でアーカイブを段階導入する際の OFF スイッチ。

    `put` は path のみ記録して何もせず、`get` は常に FileNotFoundError、
    `exists` は常に False を返す。
    """

    async def put(
        self,
        *,
        path: str,
        content: bytes,
        source_url: str,
        fetched_at: datetime,
    ) -> ArchivePut:
        return ArchivePut(backend="null", path=path)

    async def get(self, path: str) -> bytes:
        raise FileNotFoundError(f"NullArchive does not store content: {path}")

    async def exists(self, path: str) -> bool:
        return False


# ─────────────────────────────────────────────────────────────────────
# GcsArchive (本番、Cloud Storage)
# ─────────────────────────────────────────────────────────────────────


class GcsArchive:
    """Google Cloud Storage への PDF 保存 (proposal §4.5 line 204)。

    依存: `google-cloud-storage` (optional dep, `[gcs]` extra)。
    Workload Identity 経由で認証する想定 (Cloud Run Job サービスアカウントで
    `roles/storage.objectAdmin` を `fujisawa-pdf-archive` バケットに付与)。

    metadata に `source_url` / `fetched_at` を埋めるので、後で確認・dispute 解決の
    ときに「いつ・どこから取得した PDF か」を blob 単位で参照できる。
    """

    def __init__(self, *, bucket_name: str) -> None:
        if not bucket_name:
            raise ValueError("bucket_name must be non-empty")
        self._bucket_name = bucket_name
        self._client: gcs_storage.Client | None = None

    async def put(
        self,
        *,
        path: str,
        content: bytes,
        source_url: str,
        fetched_at: datetime,
    ) -> ArchivePut:
        bucket = await asyncio.to_thread(self._get_bucket)
        blob = bucket.blob(path)
        blob.metadata = {
            "source_url": source_url,
            "fetched_at": fetched_at.isoformat(),
        }
        await asyncio.to_thread(
            blob.upload_from_string,
            content,
            content_type="application/pdf",
        )
        return ArchivePut(backend="gcs", path=path)

    async def get(self, path: str) -> bytes:
        bucket = await asyncio.to_thread(self._get_bucket)
        blob = bucket.blob(path)
        return await asyncio.to_thread(blob.download_as_bytes)

    async def exists(self, path: str) -> bool:
        bucket = await asyncio.to_thread(self._get_bucket)
        blob = bucket.blob(path)
        return await asyncio.to_thread(blob.exists)

    def _get_bucket(self) -> gcs_storage.Bucket:
        if self._client is None:
            try:
                from google.cloud import storage
            except ImportError as exc:  # pragma: no cover — extra 未インストール時
                raise RuntimeError(
                    "GcsArchive requires the `google-cloud-storage` package. "
                    "Install with: `uv sync --extra gcs`"
                ) from exc
            self._client = storage.Client()
        return self._client.bucket(self._bucket_name)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _sanitize_filename(name: str) -> str:
    """ファイル名から query string と危険な文字を除去。"""
    # query string / fragment を落とす
    name = name.split("?", 1)[0].split("#", 1)[0]
    # 連続する非英数記号を - に置換、前後の - を除去
    cleaned = _INVALID_FILENAME_CHARS.sub("-", name).strip("-")
    return cleaned


def build_archive_from_config(
    *,
    backend: str,
    bucket: str | None = None,
    local_root: Path | None = None,
) -> PdfArchive:
    """`EtlConfig` から `PdfArchive` 実装を選択する factory。

    Args:
        backend: 'gcs' / 'local' / 'null' のいずれか
        bucket: backend='gcs' のとき必須
        local_root: backend='local' のとき必須

    Raises:
        ValueError: backend が未知 / 必須引数が不足
    """
    if backend == "gcs":
        if not bucket:
            raise ValueError("pdf_archive_backend='gcs' requires bucket")
        return GcsArchive(bucket_name=bucket)
    if backend == "local":
        if local_root is None:
            raise ValueError("pdf_archive_backend='local' requires local_root")
        return LocalArchive(root=local_root)
    if backend == "null":
        return NullArchive()
    raise ValueError(
        f"unknown pdf_archive_backend: {backend!r} (expected 'gcs' / 'local' / 'null')"
    )


__all__ = [
    "ArchivePut",
    "GcsArchive",
    "LocalArchive",
    "NullArchive",
    "PdfArchive",
    "archive_path",
    "build_archive_from_config",
]
