"""pytest 共通フィクスチャ。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_data_root(tmp_path: Path) -> Path:
    for sub in ("raw", "uploaded", "dead_letter", "payloads"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return tmp_path
