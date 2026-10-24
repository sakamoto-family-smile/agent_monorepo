"""資産台帳 config/services.yaml の読み込みと検証。

L0 では検証のみ。detection.db への取り込みと SBOM 生成は L2 で行う。
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

SERVICES_PATH = Path(__file__).resolve().parents[2] / "config" / "services.yaml"


class Service(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    path: str
    exposure: Literal["external", "internal", "none"]
    deployed: bool
    lockfiles: tuple[str, ...] = ()
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
