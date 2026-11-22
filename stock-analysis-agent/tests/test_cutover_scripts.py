"""cutover スクリプト (scripts/cutover/*.sh, PROPOSAL-0013) を DRY_RUN で動かし、手順の順序を確認する。

順序を間違えると、書き込み中の DB をコピーしたり、古いデータの側に LINE を向けたりするので、
「止める → コピー → 切り替える」の並びをテストで固定する。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECRETS = {
    "LINE_CHANNEL_SECRET": "line-secret-value",
    "LINE_CHANNEL_ACCESS_TOKEN": "line-token-value",
    "CLAUDE_CODE_OAUTH_TOKEN": "oauth-token-value",
    "LLM_GATEWAY_KEY": "gateway-key-value",
}


@pytest.fixture
def env_file(tmp_path) -> Path:
    path = tmp_path / "local.env"
    lines = [f"{k}={v}" for k, v in SECRETS.items()]
    lines.append("PUBLIC_BASE_URL=https://stock-analysis.tail1234.ts.net")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _dry_run(script: str, env_file: Path, tmp_path: Path) -> list[str]:
    env = {
        **os.environ,
        "DRY_RUN": "1",
        "LOCAL_ENV_FILE": str(env_file),
        "STOCK_LOCAL_DATA_DIR": str(tmp_path / "data"),
    }
    out = subprocess.run(
        ["bash", str(ROOT / "scripts" / "cutover" / script)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for value in SECRETS.values():
        assert value not in out, "秘密情報が表示されている"
    return out.splitlines()


def _index(lines: list[str], needle: str) -> int:
    for i, line in enumerate(lines):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} が出力にありません:\n" + "\n".join(lines))


def test_to_local_order(env_file, tmp_path):
    lines = _dry_run("to_local.sh", env_file, tmp_path)

    gateway_up = _index(lines, "4000/health/liveliness → HTTP 200")
    funnel_check = _index(lines, "ts.net/api/line/webhook → HTTP 405")
    stop_local = _index(lines, "stop backend")
    close_gcp = _index(lines, "remove-iam-policy-binding")
    drain = _index(lines, "が空になるまで")
    pause = _index(lines, "tasks queues pause")
    copy = _index(lines, "ops.db_copy --force")
    edinet = _index(lines, "edinet_sync.sh down")
    start_local = _index(lines, "--profile public up -d backend")
    switch = _index(lines, "ops.line_webhook set https://stock-analysis.tail1234.ts.net/api/line/webhook")
    standby = _index(lines, "terraform apply -var standby=true")

    assert gateway_up < funnel_check < stop_local < close_gcp < drain < pause < copy < edinet < start_local < switch < standby


def test_to_gcp_order(env_file, tmp_path):
    lines = _dry_run("to_gcp.sh", env_file, tmp_path)

    backup = _index(lines, "run_backup")
    stop_local = _index(lines, "stop backend")
    build = _index(lines, "builds submit")
    deploy = _index(lines, "run services update stock-analysis-line")
    push = _index(lines, "ops.secrets_sync push")
    unstandby = _index(lines, "terraform apply -var standby=false")
    resume = _index(lines, "tasks queues resume")
    copy = _index(lines, "ops.db_copy --force")
    edinet = _index(lines, "edinet_sync.sh up")
    switch = _index(lines, "ops.line_webhook set https://stock-analysis-line.example.run.app/api/line/webhook")
    down = _index(lines, "--profile public down")

    assert backup < stop_local < build < deploy < push < unstandby < resume < copy < edinet < switch < down
    # worker / webhook / EDINET Job の 3 つを同じイメージにする
    images = [line for line in lines if "--image" in line]
    assert len(images) == 3
    assert len({line.rsplit("--image ", 1)[1] for line in images}) == 1


def test_to_local_requires_public_base_url(tmp_path):
    env_file = tmp_path / "local.env"
    env_file.write_text("LINE_CHANNEL_SECRET=x\nLINE_CHANNEL_ACCESS_TOKEN=x\nCLAUDE_CODE_OAUTH_TOKEN=x\n", encoding="utf-8")

    proc = subprocess.run(
        ["bash", str(ROOT / "scripts" / "cutover" / "to_local.sh")],
        env={**os.environ, "DRY_RUN": "1", "LOCAL_ENV_FILE": str(env_file)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    assert "PUBLIC_BASE_URL" in proc.stderr
