"""ローカル疑似アップローダ (raw → uploaded、失敗時 dead_letter)。

設計書 §9.3.2 の GCS Uploader を、ローカルでは単なる `os.rename` で代替する。
本番 (GCP) では同じインターフェースを GCSUploader に差し替える想定。

冪等性:
  - ファイル名は `{service}_{event_type}_{dt}_{hour}.jsonl[.gz]` で一意
  - 移動先に同名ファイルがあれば追記マージではなく suffix を付けて保存
    (取り込み側が `read_json_auto` で全ファイル読むのでレコード重複は後段で排除)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tenacity import (
    AsyncRetrying,
    RetryError,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class UploadTransport(Protocol):
    """raw ファイル 1 本を宛先に送る最小インターフェース。"""

    async def send(self, src: Path, *, dest_root: Path) -> Path: ...


# ---------------------------------------------------------------------------
# ローカル = ただの rename
# ---------------------------------------------------------------------------


@dataclass
class LocalMoveTransport:
    """`raw/...` 以下の相対パス構造をそのまま `dest_root/...` に保持して移動する。

    fail_probability を 0 < p <= 1 で設定するとテストから擬似失敗を起こせる。
    """

    raw_root: Path
    fail_probability: float = 0.0
    _rng: Callable[[], float] | None = None

    async def send(self, src: Path, *, dest_root: Path) -> Path:
        if self._rng is not None and self._rng() < self.fail_probability:
            raise OSError(f"simulated upload failure: {src}")

        rel = src.relative_to(self.raw_root)
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        # 同名ファイル衝突時は suffix 追加
        if dest.exists():
            dest = dest.with_name(f"{dest.stem}.{int(time.time() * 1000)}{dest.suffix}")
        await asyncio.to_thread(src.rename, dest)
        return dest


# ---------------------------------------------------------------------------
# 結果
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UploadOutcome:
    uploaded: list[Path]
    dead_letter: list[Path]

    @property
    def total(self) -> int:
        return len(self.uploaded) + len(self.dead_letter)


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------


@dataclass
class LocalUploader:
    raw_root: Path
    uploaded_root: Path
    dead_letter_root: Path
    transport: UploadTransport
    min_age_seconds: float = 0.0  # 書込直後のファイルを避けるためのヒステリシス
    max_attempts: int = 5
    backoff_multiplier: float = 1.0
    backoff_max: float = 16.0

    def _list_raw_files(self) -> list[Path]:
        if not self.raw_root.exists():
            return []
        now = time.time()
        result: list[Path] = []
        for path in sorted(self.raw_root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix not in (".jsonl", ".gz"):
                continue
            if self.min_age_seconds and now - path.stat().st_mtime < self.min_age_seconds:
                continue
            result.append(path)
        return result

    async def _try_upload(self, src: Path) -> Path:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=self.backoff_multiplier, max=self.backoff_max),
            reraise=True,
        ):
            with attempt:
                return await self.transport.send(src, dest_root=self.uploaded_root)
        raise RuntimeError("unreachable")  # pragma: no cover

    async def _move_to_dead_letter(self, src: Path) -> Path:
        rel = src.relative_to(self.raw_root)
        dest = self.dead_letter_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = dest.with_name(f"{dest.stem}.{int(time.time() * 1000)}{dest.suffix}")
        await asyncio.to_thread(src.rename, dest)
        return dest

    async def run_once(self) -> UploadOutcome:
        """raw_root 配下の 1 バッチを処理して UploadOutcome を返す。"""
        self.uploaded_root.mkdir(parents=True, exist_ok=True)
        self.dead_letter_root.mkdir(parents=True, exist_ok=True)

        uploaded: list[Path] = []
        dead: list[Path] = []
        for src in self._list_raw_files():
            try:
                dest = await self._try_upload(src)
                uploaded.append(dest)
            except RetryError:
                dead.append(await self._move_to_dead_letter(src))
                logger.error("upload moved to dead_letter: %s", src)
            except Exception:
                dead.append(await self._move_to_dead_letter(src))
                logger.exception("upload failed (non-retryable): %s", src)
        return UploadOutcome(uploaded=uploaded, dead_letter=dead)
