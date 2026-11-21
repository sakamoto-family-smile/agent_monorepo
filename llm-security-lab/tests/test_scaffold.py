"""Phase 0a 用 smoke test。 scaffold が import エラーなくロードできることを
確認する最低限のテスト。 Phase 0b 以降で `shared/llm_runtime/` 等の実装テストを
追加する。
"""

from __future__ import annotations

from pathlib import Path

import shared


def test_shared_package_importable() -> None:
    """`shared` パッケージが正常にロードできる。"""
    assert hasattr(shared, "__version__")
    assert shared.__version__ == "0.1.0"


def test_pyproject_exists() -> None:
    """`pyproject.toml` が存在し名前が正しい。"""
    root = Path(__file__).parent.parent
    pyproject = root / "pyproject.toml"
    assert pyproject.exists(), "pyproject.toml is missing"
    content = pyproject.read_text(encoding="utf-8")
    assert 'name = "llm-security-lab"' in content


def test_docker_compose_exists_with_localhost_binding() -> None:
    """`docker-compose.yml` が存在し、 JupyterLab port が 127.0.0.1 にバインド
    されている (proposal §3.9 リスク対応の regression test)。
    """
    root = Path(__file__).parent.parent
    compose = root / "docker-compose.yml"
    assert compose.exists(), "docker-compose.yml is missing"
    content = compose.read_text(encoding="utf-8")
    # JupyterLab の host port は必ず 127.0.0.1 でバインド (外部 expose 防止)
    assert "127.0.0.1:8888:8888" in content, (
        "JupyterLab port must bind to 127.0.0.1 only (proposal-0008 §3.9)"
    )
    # 0.0.0.0:8888 で host バインドしていないことも確認 (regression)
    assert "0.0.0.0:8888:8888" not in content


def test_env_example_warns_default_token() -> None:
    """`.env.example` がデフォルト token の置き換え指示を含む。"""
    root = Path(__file__).parent.parent
    env_example = root / ".env.example"
    assert env_example.exists()
    content = env_example.read_text(encoding="utf-8")
    assert "JUPYTER_TOKEN" in content
    assert "CHANGE_ME" in content  # 置き換えが必要であることを明示
