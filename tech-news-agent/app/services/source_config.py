"""sources.yaml ローダ。

priority (1/2/3) → source_weight (0.7 / 1.0 / 1.5) のマッピングもここに集約。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

SourceType = Literal["rss", "arxiv"]

_PRIORITY_TO_WEIGHT: dict[int, float] = {
    1: 0.7,
    2: 1.0,
    3: 1.5,
}


@dataclass(frozen=True)
class RssSourceConfig:
    name: str
    url: str
    priority: int
    weight: float


@dataclass(frozen=True)
class ArxivSourceConfig:
    name: str
    categories: tuple[str, ...]
    rate_limit_seconds: int
    max_results: int
    priority: int
    weight: float


@dataclass(frozen=True)
class SourcesConfig:
    domain: str
    rss: tuple[RssSourceConfig, ...]
    arxiv: tuple[ArxivSourceConfig, ...]


def _weight_of(priority: int) -> float:
    return _PRIORITY_TO_WEIGHT.get(priority, 1.0)


def load_sources(path: str | Path) -> SourcesConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"sources.yaml must be a mapping, got {type(raw).__name__}")
    domain = str(raw.get("domain", "data_platform"))
    rss: list[RssSourceConfig] = []
    arxiv: list[ArxivSourceConfig] = []
    for src in raw.get("sources") or []:
        st = src.get("type")
        priority = int(src.get("priority", 2))
        weight = _weight_of(priority)
        if st == "rss":
            rss.append(
                RssSourceConfig(
                    name=src["name"],
                    url=src["url"],
                    priority=priority,
                    weight=weight,
                )
            )
        elif st == "arxiv":
            arxiv.append(
                ArxivSourceConfig(
                    name=src.get("name", "arxiv"),
                    categories=tuple(src.get("categories") or []),
                    rate_limit_seconds=int(src.get("rate_limit_seconds", 3)),
                    max_results=int(src.get("max_results", 50)),
                    priority=priority,
                    weight=weight,
                )
            )
        else:
            # 未知 type は warning 出しつつスキップ (落とさない)
            continue
    return SourcesConfig(domain=domain, rss=tuple(rss), arxiv=tuple(arxiv))
