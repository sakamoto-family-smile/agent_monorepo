"""PR 1: seed_events.py のバリデーションと dry-run 挙動。

DB 投入は scripts/seed_events.py の async 関数を直接呼ぶ統合テストで検証する。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def seed_module():
    """scripts/seed_events をロード (sys.path に scripts/ を追加)。"""
    import sys

    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import seed_events

    return seed_events


# ---- _validate ----


def test_validate_accepts_valid_events(seed_module):
    seed_module._validate(
        [
            {
                "event_type": "E01",
                "start_year": 2026,
                "params": {"birth_year": 2026},
            },
            {
                "event_type": "E02",
                "start_year": 2028,
                "params": {"price": 60_000_000},
            },
        ]
    )


def test_validate_rejects_unsupported_event_type(seed_module):
    with pytest.raises(ValueError, match="unsupported event_type"):
        seed_module._validate(
            [{"event_type": "E03", "start_year": 2030, "params": {}}]
        )


def test_validate_rejects_missing_field(seed_module):
    with pytest.raises(ValueError, match="missing required field"):
        seed_module._validate([{"event_type": "E01"}])  # start_year なし


def test_validate_rejects_non_int_year(seed_module):
    with pytest.raises(ValueError, match="start_year must be int"):
        seed_module._validate(
            [{"event_type": "E01", "start_year": "2026"}]
        )


def test_validate_rejects_non_dict_params(seed_module):
    with pytest.raises(ValueError, match="params must be dict"):
        seed_module._validate(
            [{"event_type": "E01", "start_year": 2026, "params": []}]
        )


# ---- example JSON は valid ----


def test_example_seed_file_passes_validation(seed_module):
    """data/seeds/example_events.json は常に valid であること。"""
    repo_root = Path(__file__).resolve().parent.parent
    path = repo_root / "data" / "seeds" / "example_events.json"
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    seed_module._validate(data["events"])
    assert len(data["events"]) >= 1
