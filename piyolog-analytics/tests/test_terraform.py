"""Terraform IaC のスモークテスト (Step B3)。

Apply は実 GCP にしか走らないため、ここでは:
  - terraform CLI があれば fmt -check + validate を実行
  - 主要ファイルが揃っていることをパス確認
  - tfvars.example に実 project id 等が漏れていないこと

CI で terraform CLI が無い環境では fmt/validate を skip するだけで pass する。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TF_DIR = REPO_ROOT / "terraform"

REQUIRED_FILES = [
    "versions.tf",
    "variables.tf",
    "locals.tf",
    "outputs.tf",
    "cloud_sql.tf",
    "secrets.tf",
    "iam.tf",
    "artifact_registry.tf",
    "cloudbuild-plan.yaml",
    "cloudbuild-drift.yaml",
    "README.md",
    "terraform.tfvars.example",
    ".gitignore",
]


def test_terraform_directory_exists() -> None:
    assert TF_DIR.exists() and TF_DIR.is_dir()


@pytest.mark.parametrize("fname", REQUIRED_FILES)
def test_required_files_present(fname: str) -> None:
    assert (TF_DIR / fname).exists(), f"missing {fname}"


def test_tfvars_example_uses_env_for_project_id() -> None:
    """`project_id` は env (TF_VAR_project_id) で渡す方針。tfvars.example に hardcode 禁止。"""
    body = (TF_DIR / "terraform.tfvars.example").read_text()
    # env 方針が明文化されていること
    assert "TF_VAR_project_id" in body, "tfvars.example should document TF_VAR_project_id env"
    # `project_id = "..."` のハードコードがないこと (コメント行は許容)
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        assert not stripped.startswith("project_id"), (
            f"tfvars.example must not hardcode project_id; use TF_VAR_project_id env. line={line!r}"
        )
    # 実環境 project id が誤って書かれていないこと
    forbidden = ["youyaku-ai", "kanie-lab", "sakamoto-"]
    for s in forbidden:
        assert s not in body, f"placeholder leaked real project hint: {s}"


def test_gitignore_excludes_state_and_tfvars() -> None:
    body = (TF_DIR / ".gitignore").read_text()
    for must in ("*.tfstate", "terraform.tfvars", ".terraform/"):
        assert must in body, f".gitignore missing {must}"


def test_secrets_tf_does_not_hardcode_secrets() -> None:
    """`secrets.tf` 自体に LINE token 値が混入していないこと (簡易チェック)。"""
    body = (TF_DIR / "secrets.tf").read_text()
    # LINE access token は通常 EAA で始まる長い文字列
    assert "EAA" not in body
    # `secret_data = "..."` の固定文字列がないこと (var. 経由のみ許す)
    forbidden_patterns = ['secret_data = "EAA', 'secret_data = "U']
    for pat in forbidden_patterns:
        assert pat not in body, f"hardcoded secret-like string in secrets.tf: {pat}"


def test_iam_tf_grants_sa_piyolog_required_roles() -> None:
    body = (TF_DIR / "iam.tf").read_text()
    for role in (
        "roles/cloudsql.client",
        "roles/secretmanager.secretAccessor",
        "roles/artifactregistry.reader",
    ):
        assert role in body, f"sa-piyolog missing role: {role}"


def test_cloud_sql_password_is_random_generated() -> None:
    """random_password で生成し、tfvars / config に平文を持たないこと。"""
    body = (TF_DIR / "cloud_sql.tf").read_text()
    assert 'resource "random_password" "cloud_sql_db_password"' in body
    assert "google_sql_user" in body and "random_password.cloud_sql_db_password.result" in body


# --------------------------------------------------------------------------
# Cloud Build CI yaml (Q2: plan-only PR + drift detection)
# --------------------------------------------------------------------------


def test_cloudbuild_plan_is_plan_only() -> None:
    """PR plan-only は `terraform apply` を絶対に呼ばない。"""
    body = (TF_DIR / "cloudbuild-plan.yaml").read_text()
    assert "terraform plan" in body
    # apply / destroy が含まれていないこと
    assert "terraform apply" not in body
    assert "terraform destroy" not in body
    # TF_VAR_project_id を env で渡している
    assert "TF_VAR_project_id" in body


def test_cloudbuild_drift_uses_detailed_exitcode() -> None:
    """Drift 検知は -detailed-exitcode を使い、exit=2 を escalate する。"""
    body = (TF_DIR / "cloudbuild-drift.yaml").read_text()
    assert "-detailed-exitcode" in body
    # apply は呼ばない
    assert "terraform apply" not in body
    # drift detected の警告メッセージが含まれている
    assert "DRIFT DETECTED" in body


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform CLI not installed")
def test_terraform_fmt_check() -> None:
    proc = subprocess.run(
        ["terraform", "fmt", "-check", "-recursive", "-diff"],
        capture_output=True,
        text=True,
        cwd=TF_DIR,
        check=False,
    )
    assert proc.returncode == 0, f"terraform fmt -check failed:\n{proc.stdout}\n{proc.stderr}"


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform CLI not installed")
def test_terraform_validate() -> None:
    init = subprocess.run(
        ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
        capture_output=True,
        text=True,
        cwd=TF_DIR,
        check=False,
    )
    assert init.returncode == 0, f"terraform init failed:\n{init.stdout}\n{init.stderr}"

    validate = subprocess.run(
        ["terraform", "validate", "-no-color"],
        capture_output=True,
        text=True,
        cwd=TF_DIR,
        check=False,
    )
    assert validate.returncode == 0, f"terraform validate failed:\n{validate.stdout}\n{validate.stderr}"
