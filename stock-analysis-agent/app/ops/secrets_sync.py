"""config/local.env と Secret Manager の秘密情報を同期する (PROPOSAL-0013 の cutover 用)。

    uv run python -m ops.secrets_sync diff   # 値が違うキーの名前だけを表示
    uv run python -m ops.secrets_sync pull   # Secret Manager → config/local.env
    uv run python -m ops.secrets_sync push   # config/local.env → Secret Manager (違うものだけ新しい version を追加)

値はどこにも表示しない。Secret の値は gcloud の stdin / stdout でだけやり取りする。
Secret 名は terraform/locals.tf の `<service_name>-<name>` と同じ。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / "config" / "local.env"

# env のキー → Secret 名の後半 (terraform/locals.tf)
SECRET_KEYS: dict[str, str] = {
    "LINE_CHANNEL_SECRET": "line-channel-secret",
    "LINE_CHANNEL_ACCESS_TOKEN": "line-channel-access-token",
    "CLAUDE_CODE_OAUTH_TOKEN": "claude-code-oauth-token",
    "BRAVE_API_KEY": "brave-api-key",
    "EDINET_API_KEY": "edinet-api-key",
}

# gcloud を呼ぶ関数: (引数, stdin) → stdout。失敗時は例外
Runner = Callable[[list[str], str | None], str]


class SyncError(RuntimeError):
    pass


def gcloud_runner(args: list[str], stdin: str | None) -> str:
    proc = subprocess.run(["gcloud", *args], input=stdin, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        # stderr に値は出ないが、念のため短く
        raise SyncError(f"gcloud {' '.join(args[:3])} に失敗しました: {proc.stderr.strip()[:300]}")
    return proc.stdout


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, sep, value = stripped.partition("=")
        if sep:
            values[name.strip()] = value.strip()
    return values


def write_env_values(path: Path, updates: dict[str, str]) -> None:
    """既存の KEY= 行だけを書き換える (コメントや並びはそのまま)。無いキーは末尾に足す。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    out = []
    for line in lines:
        name, sep, _ = line.strip().partition("=")
        key = name.strip()
        if sep and not line.lstrip().startswith("#") and key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in remaining.items()]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


class SecretStore:
    def __init__(self, *, project: str, service_name: str, runner: Runner = gcloud_runner) -> None:
        self._project = project
        self._service = service_name
        self._run = runner

    def secret_id(self, key: str) -> str:
        return f"{self._service}-{SECRET_KEYS[key]}"

    def get(self, key: str) -> str | None:
        try:
            out = self._run(
                ["secrets", "versions", "access", "latest", "--project", self._project, "--secret", self.secret_id(key)],
                None,
            )
        except SyncError:
            return None  # version が無い (EDINET 無効時など)
        return out.rstrip("\n")

    def add(self, key: str, value: str) -> None:
        self._run(
            ["secrets", "versions", "add", self.secret_id(key), "--project", self._project, "--data-file=-"],
            value,
        )


def diff_keys(local: dict[str, str], store: SecretStore) -> list[str]:
    return [key for key in SECRET_KEYS if (local.get(key) or None) != store.get(key)]


def pull(env_file: Path, store: SecretStore) -> list[str]:
    local = read_env(env_file)
    updates = {}
    for key in SECRET_KEYS:
        remote = store.get(key)
        if remote is not None and remote != local.get(key):
            updates[key] = remote
    if updates:
        write_env_values(env_file, updates)
    return sorted(updates)


def push(env_file: Path, store: SecretStore) -> list[str]:
    local = read_env(env_file)
    pushed = []
    for key in SECRET_KEYS:
        value = local.get(key, "")
        if value and value != store.get(key):
            store.add(key, value)
            pushed.append(key)
    return pushed


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="config/local.env と Secret Manager の秘密情報を同期する")
    p.add_argument("command", choices=["diff", "pull", "push"])
    p.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    p.add_argument("--project", default=os.getenv("PROJECT_ID", "sakamomo-family-agent"))
    p.add_argument("--service-name", default=os.getenv("SERVICE_NAME", "stock-analysis-line"))
    return p.parse_args(argv)


def main(argv: list[str] | None = None, *, runner: Runner = gcloud_runner) -> int:
    args = _parse_args(argv)
    if not args.env_file.exists():
        print(f"{args.env_file} がありません (config/local.env.example から作ってください)", file=sys.stderr)
        return 2
    store = SecretStore(project=args.project, service_name=args.service_name, runner=runner)
    try:
        if args.command == "diff":
            keys = diff_keys(read_env(args.env_file), store)
            print("差分あり: " + ", ".join(keys) if keys else "差分なし")
        elif args.command == "pull":
            keys = pull(args.env_file, store)
            print("config/local.env を更新しました: " + ", ".join(keys) if keys else "更新なし")
        else:
            keys = push(args.env_file, store)
            print("Secret Manager に追加しました: " + ", ".join(keys) if keys else "追加なし")
    except SyncError as e:
        print(f"失敗: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
