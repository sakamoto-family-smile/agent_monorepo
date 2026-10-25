"""config/services.yaml (資産台帳) がリポジトリの実態と一致しているかのテスト。"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.common.services import load_services

MONOREPO = Path(__file__).resolve().parents[3]


def test_services_yaml_is_valid_and_paths_exist():
    services = load_services()
    assert services
    for s in services:
        assert (MONOREPO / s.path).is_dir(), s.path
        for lock in s.lockfiles:
            assert (MONOREPO / s.path / lock).is_file(), f"{s.path}{lock}"


def test_auto_remediation_requires_lockfile():
    for s in load_services():
        if s.auto_remediation:
            assert s.lockfiles, f"{s.id}: auto_remediation には lockfile が必要"


def test_rejects_duplicates_and_escaping_paths(tmp_path):
    bad = tmp_path / "services.yaml"
    bad.write_text("services:\n  - {id: a, path: a/, exposure: none, deployed: false}\n"
                   "  - {id: a, path: b/, exposure: none, deployed: false}\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_services(bad)
    bad.write_text("services:\n  - {id: a, path: ../x, exposure: none, deployed: false}\n")
    with pytest.raises(ValueError):
        load_services(bad)
