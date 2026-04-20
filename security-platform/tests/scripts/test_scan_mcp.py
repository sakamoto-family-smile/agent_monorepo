"""Behavioural tests for scripts/scan-mcp.sh.

The script reads its target list from config/scan.yaml and scans each entry
with `uvx snyk-agent-scan`. These tests build an isolated mirror of the
expected repo layout, stub `uvx` with a deterministic fake, and verify:

- Each existing target produces an output file at the expected slug.
- Missing targets are skipped without aborting the run.
- The YAML-driven target list in the real config exposes lifeplanner-agent
  source_code and intentionally omits MCP configs that do not exist.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


SECURITY_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
REAL_SCRIPT = SECURITY_PLATFORM_ROOT / "scripts" / "scan-mcp.sh"
REAL_CONFIG = SECURITY_PLATFORM_ROOT / "config" / "scan.yaml"


# ---------------------------------------------------------------------------
# Harness helpers
# ---------------------------------------------------------------------------


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _write_fake_uvx(bin_dir: Path) -> None:
    """Stub uvx so the scan step runs without network or snyk availability.

    Emits a deterministic JSON body containing the arguments it received so
    tests can assert the script forwarded the right path.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "uvx"
    fake.write_text(
        "#!/bin/bash\n"
        "printf '{\"fake_uvx\":true,\"args\":\"%s\"}\\n' \"$*\"\n"
    )
    _make_executable(fake)


def _write_python3_shim(bin_dir: Path) -> None:
    """Expose the pytest interpreter (which has PyYAML) as `python3` on PATH.

    The script's pure-Python fallback invokes `python3`; the system python3
    may not have PyYAML installed, so we route it at the test venv. A thin
    bash wrapper is used rather than a symlink so `pyvenv.cfg` beside the
    real interpreter is still discovered and site-packages stays wired up.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "python3"
    if shim.exists() or shim.is_symlink():
        shim.unlink()
    shim.write_text(f'#!/bin/bash\nexec "{sys.executable}" "$@"\n')
    _make_executable(shim)


def _build_mirror(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal mirror of the monorepo the script expects.

    Returns (repo_root, security_platform_dir).
    """
    repo = tmp_path / "monorepo"
    sp = repo / "security-platform"
    (sp / "scripts").mkdir(parents=True)
    (sp / "config").mkdir(parents=True)
    (sp / "logs").mkdir(parents=True)

    dest_script = sp / "scripts" / "scan-mcp.sh"
    shutil.copy(REAL_SCRIPT, dest_script)
    _make_executable(dest_script)

    return repo, sp


def _run_script(
    script_path: Path,
    repo_root: Path,
    bin_dir: Path,
) -> subprocess.CompletedProcess[str]:
    """Invoke the script with a scrubbed PATH that excludes any host `yq`.

    Dropping `yq` forces the python3 fallback, which is the code path most
    likely to fail silently in environments without yq installed.
    """
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    return subprocess.run(
        ["bash", str(script_path)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


# ---------------------------------------------------------------------------
# Script behaviour
# ---------------------------------------------------------------------------


def test_scans_each_target_listed_in_scan_yaml(tmp_path: Path) -> None:
    repo, sp = _build_mirror(tmp_path)

    (sp / "config" / "scan.yaml").write_text(
        "targets:\n"
        "  mcp_configs:\n"
        '    - "agent-one/.mcp.json"\n'
        '    - "agent-two/.mcp.json"\n'
    )
    (repo / "agent-one").mkdir()
    (repo / "agent-one" / ".mcp.json").write_text("{}")
    (repo / "agent-two").mkdir()
    (repo / "agent-two" / ".mcp.json").write_text("{}")

    bin_dir = tmp_path / "bin"
    _write_fake_uvx(bin_dir)
    _write_python3_shim(bin_dir)

    result = _run_script(sp / "scripts" / "scan-mcp.sh", repo, bin_dir)
    assert result.returncode == 0, result.stderr

    logs = sp / "logs"
    expected_files = {
        logs / "mcp-scan-agent-one--mcp-json.json",
        logs / "mcp-scan-agent-two--mcp-json.json",
    }
    produced = set(logs.glob("mcp-scan-*.json"))
    assert produced == expected_files

    for f in expected_files:
        assert "fake_uvx" in f.read_text()


def test_skips_missing_targets_without_failing_the_run(tmp_path: Path) -> None:
    repo, sp = _build_mirror(tmp_path)

    (sp / "config" / "scan.yaml").write_text(
        "targets:\n"
        "  mcp_configs:\n"
        '    - "agent-present/.mcp.json"\n'
        '    - "agent-missing/.mcp.json"\n'
    )
    (repo / "agent-present").mkdir()
    (repo / "agent-present" / ".mcp.json").write_text("{}")
    # agent-missing intentionally not created

    bin_dir = tmp_path / "bin"
    _write_fake_uvx(bin_dir)
    _write_python3_shim(bin_dir)

    result = _run_script(sp / "scripts" / "scan-mcp.sh", repo, bin_dir)
    assert result.returncode == 0, result.stderr

    logs = sp / "logs"
    assert (logs / "mcp-scan-agent-present--mcp-json.json").exists()
    assert not (logs / "mcp-scan-agent-missing--mcp-json.json").exists()

    assert "SKIP (missing): agent-missing/.mcp.json" in result.stdout
    assert "Scanning: agent-present/.mcp.json" in result.stdout


def test_empty_mcp_configs_list_is_noop(tmp_path: Path) -> None:
    repo, sp = _build_mirror(tmp_path)

    (sp / "config" / "scan.yaml").write_text(
        "targets:\n"
        "  mcp_configs: []\n"
    )

    bin_dir = tmp_path / "bin"
    _write_fake_uvx(bin_dir)
    _write_python3_shim(bin_dir)

    result = _run_script(sp / "scripts" / "scan-mcp.sh", repo, bin_dir)
    assert result.returncode == 0, result.stderr

    produced = list((sp / "logs").glob("mcp-scan-*.json"))
    assert produced == []
    assert "Scan Complete" in result.stdout


# ---------------------------------------------------------------------------
# Real config/scan.yaml
# ---------------------------------------------------------------------------


def test_real_scan_yaml_is_valid_and_lists_expected_targets() -> None:
    data = yaml.safe_load(REAL_CONFIG.read_text())
    targets = data.get("targets") or {}

    mcp_configs = targets.get("mcp_configs") or []
    source_directories = targets.get("source_directories") or []

    # Only agents that actually check an .mcp.json into the repo belong here.
    # stock-analysis-agent generates one at runtime under a gitignored dir;
    # lifeplanner-agent does not use MCP.
    assert "agent-system-1/.mcp.json" in mcp_configs
    assert "agent-system-2/.mcp.json" in mcp_configs
    assert "kanie-lab-agent/.mcp.json" in mcp_configs
    for path in mcp_configs:
        assert not path.startswith("lifeplanner-agent/"), (
            "lifeplanner-agent does not ship an .mcp.json"
        )

    # lifeplanner-agent source code must be covered by the source scan.
    assert "lifeplanner-agent/app/" in source_directories
    assert "stock-analysis-agent/app/" in source_directories


def test_real_scan_yaml_mcp_paths_exist_or_are_intentionally_missing() -> None:
    """Guard against silently referencing a renamed/removed agent.

    Any path listed in mcp_configs must either exist at the repo root, or
    be removed from scan.yaml. We resolve the monorepo root relative to
    this test file so the check runs without requiring a checkout-time env.
    """
    monorepo_root = SECURITY_PLATFORM_ROOT.parent
    data = yaml.safe_load(REAL_CONFIG.read_text())
    mcp_configs = (data.get("targets") or {}).get("mcp_configs") or []

    missing = [p for p in mcp_configs if not (monorepo_root / p).exists()]
    assert not missing, (
        "scan.yaml references MCP configs that do not exist in the repo: "
        f"{missing}. Either add the file or remove it from scan.yaml."
    )
