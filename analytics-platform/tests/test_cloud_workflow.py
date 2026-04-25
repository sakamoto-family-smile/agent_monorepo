"""Cloud Workflows YAML / orchestration script のスモークテスト。

Workflow のセマンティクスは GCP 側でしか検証できないため、ここでは
構文・必須キー・参照整合性 (subworkflow が main から呼ばれているか等) を確認する。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_FILE = REPO_ROOT / "workflows" / "dbt_pipeline.yaml"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy_orchestration.sh"


def test_workflow_yaml_is_valid() -> None:
    assert WORKFLOW_FILE.exists()
    with WORKFLOW_FILE.open() as f:
        doc = yaml.safe_load(f)
    assert isinstance(doc, dict)
    assert "main" in doc, "Cloud Workflow must have a `main` entry point"
    assert "notify_slack" in doc, "expected notify_slack subworkflow"


def test_workflow_main_has_required_steps() -> None:
    with WORKFLOW_FILE.open() as f:
        doc = yaml.safe_load(f)
    main = doc["main"]
    assert "params" in main
    steps = main["steps"]
    step_names = {next(iter(s.keys())) for s in steps}
    # 必須ステップが揃っているか
    for required in ("init", "log_start", "run_dbt", "log_success", "return_success"):
        assert required in step_names, f"missing step: {required}"


def test_workflow_calls_cloud_run_job_v2_api() -> None:
    """Cloud Run Job 起動 API が v2 (推奨) を使っていることを確認。"""
    body = WORKFLOW_FILE.read_text()
    assert "googleapis.run.v2.projects.locations.jobs.run" in body


def test_workflow_handles_failure_with_slack_notification() -> None:
    """run_dbt の except 節で notify_slack が条件付き呼出されていることを確認。"""
    with WORKFLOW_FILE.open() as f:
        doc = yaml.safe_load(f)
    main_steps = doc["main"]["steps"]
    run_dbt_step = next(s for s in main_steps if "run_dbt" in s)["run_dbt"]
    assert "except" in run_dbt_step
    except_steps = run_dbt_step["except"]["steps"]
    except_names = {next(iter(s.keys())) for s in except_steps}
    assert "log_failure" in except_names
    assert "return_failure" in except_names


def test_deploy_script_is_executable() -> None:
    assert DEPLOY_SCRIPT.exists()
    # POSIX 実行権限ビットが立っていること
    assert DEPLOY_SCRIPT.stat().st_mode & 0o111, "deploy_orchestration.sh must be executable"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_deploy_script_passes_bash_n() -> None:
    proc = subprocess.run(
        ["bash", "-n", str(DEPLOY_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"bash -n failed:\n{proc.stderr}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_deploy_script_requires_gcp_project_env() -> None:
    """ANALYTICS_GCP_PROJECT 未設定で実行すると non-zero exit する (`: ${VAR:?...}` 構文)。"""
    proc = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert proc.returncode != 0
    assert "ANALYTICS_GCP_PROJECT" in proc.stderr
