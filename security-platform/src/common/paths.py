"""data/ 配下のレイアウト。

生データ・運用 DB・分析 DB・イベントログの置き場所を 1 か所で決める。
サブシステムはパスを直書きせず、必ずここから取る。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import settings

DB_NAMES: tuple[str, ...] = ("intel", "detection", "remediation", "notify")


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @property
    def raw_dir(self) -> Path:
        return self.root / "raw"

    @property
    def events_dir(self) -> Path:
        return self.root / "events"

    @property
    def osv_db_dir(self) -> Path:
        """osv-scanner のオフライン DB (``<dir>/osv-scanner/<ecosystem>/all.zip``)。"""
        return self.root / "osv-db"

    @property
    def sbom_images_dir(self) -> Path:
        """本番イメージの SBOM (``make detection-images`` が作る。<service_id>.json と blobs/)。"""
        return self.root / "sbom" / "images"

    @property
    def duckdb_path(self) -> Path:
        return self.root / "security.duckdb"

    def sqlite_path(self, name: str) -> Path:
        if name not in DB_NAMES:
            raise ValueError(f"unknown database: {name}")
        return self.root / f"{name}.db"

    def ensure(self) -> None:
        for d in (self.root, self.raw_dir, self.events_dir, self.osv_db_dir, self.sbom_images_dir):
            d.mkdir(parents=True, exist_ok=True)


def default_paths() -> DataPaths:
    return DataPaths(Path(settings.data_dir))
