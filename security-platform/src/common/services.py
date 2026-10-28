"""資産台帳 config/services.yaml の読み込みと検証。

detection が照合のたびに読み、detection.db の services に写す。
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

SERVICES_PATH = Path(__file__).resolve().parents[2] / "config" / "services.yaml"


class ImageRef(BaseModel):
    """本番で動いているコンテナイメージの取り出し元 (Cloud Run のサービスかジョブのどちらか)。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cloud_run: str | None = None
    cloud_run_job: str | None = None
    region: str = "asia-northeast1"

    @model_validator(mode="after")
    def _exactly_one(self) -> ImageRef:
        if (self.cloud_run is None) == (self.cloud_run_job is None):
            raise ValueError("images: cloud_run か cloud_run_job のどちらか 1 つを指定する")
        return self

    @property
    def key(self) -> str:
        """SBOM の置き場所と照合結果で使う識別子 (例: ``cloud_run:stock-analysis-line``)。"""
        if self.cloud_run is not None:
            return f"cloud_run:{self.cloud_run}"
        return f"cloud_run_job:{self.cloud_run_job}"


class Service(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    path: str
    exposure: Literal["external", "internal", "none"]
    deployed: bool
    lockfiles: tuple[str, ...] = ()
    images: tuple[ImageRef, ...] = ()
    auto_remediation: bool = False

    @field_validator("path")
    @classmethod
    def _relative_dir(cls, v: str) -> str:
        if v.startswith("/") or ".." in Path(v).parts:
            raise ValueError("path must be relative to the monorepo root")
        return v if v.endswith("/") else f"{v}/"


def load_services(path: Path = SERVICES_PATH) -> list[Service]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    services = [Service(**s) for s in data.get("services") or []]
    ids = [s.id for s in services]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"duplicate service ids: {dupes}")
    return services
