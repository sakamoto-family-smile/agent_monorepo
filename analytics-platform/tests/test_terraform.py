"""Terraform IaC のスモークテスト。

Apply は実 GCP にしか走らないため、ここでは:
  - terraform CLI があれば fmt -check + validate を実行
  - 主要ファイルが揃っていることをパス確認

CI で terraform CLI が無い環境でも skip するだけで pass する。
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
    "gcs.tf",
    "artifact_registry.tf",
    "bigquery.tf",
    "iam.tf",
    "README.md",
    "terraform.tfvars.example",
    ".gitignore",
]


def test_terraform_directory_exists() -> None:
    assert TF_DIR.exists()
    assert TF_DIR.is_dir()


@pytest.mark.parametrize("fname", REQUIRED_FILES)
def test_required_files_present(fname: str) -> None:
    assert (TF_DIR / fname).exists(), f"missing {fname}"


def test_tfvars_example_does_not_contain_real_project_id() -> None:
    """tfvars.example は placeholder のままであること (実 project id を commit しない)。"""
    body = (TF_DIR / "terraform.tfvars.example").read_text()
    assert "your-gcp-project-id" in body or "PROJECT_ID" in body
    # 実環境っぽい文字列が混じっていないこと (簡易チェック)
    forbidden = ["youyaku-ai", "kanie-lab", "sakamoto-"]
    for s in forbidden:
        assert s not in body, f"placeholder leaked real project hint: {s}"


def test_gitignore_excludes_state_and_tfvars() -> None:
    body = (TF_DIR / ".gitignore").read_text()
    for must in ("*.tfstate", "terraform.tfvars", ".terraform/"):
        assert must in body, f".gitignore missing {must}"


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
    """`terraform init -backend=false` + `terraform validate`。

    backend init 不要 (-backend=false) なので credentials 無しでも実行可能。
    .terraform/ は .gitignore 済なので残骸は気にしない。
    """
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
