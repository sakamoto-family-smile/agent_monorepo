"""エージェント用のバーチャルキーを発行する (PROPOSAL-0014)。

    python3 scripts/issue_key.py stock-analysis-agent --models stock-analysis,stock-analysis-next \
        --env-file ../stock-analysis-agent/config/local.env

キーは --env-file の LLM_GATEWAY_KEY に書き込み、画面には出さない (--env-file を省くと標準出力に出す)。
マスターキーは config/gateway.env から読む。標準ライブラリだけで動く。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_KEY = "LLM_GATEWAY_KEY"


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and not name.startswith("#"):
            values[name.strip()] = value.strip()
    return values


def set_env_value(path: Path, name: str, value: str) -> None:
    """name=value を置き換える (無ければ末尾に足す)。ほかの行と権限はそのまま。"""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, done = [], False
    for line in lines:
        if line.strip().partition("=")[0].strip() == name:
            out.append(f"{name}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{name}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def build_request(alias: str, models: list[str], budget: float, rpm: int) -> dict:
    return {
        "key_alias": alias,
        "models": models,
        "max_budget": budget,
        "budget_duration": "30d",  # 30 日ごとに利用額を戻す
        "rpm_limit": rpm,
        "metadata": {"issued_by": "llm-gateway/scripts/issue_key.py"},
    }


def generate(url: str, master_key: str, body: dict) -> str:
    req = urllib.request.Request(
        f"{url}/key/generate",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {master_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:  # nosec B310  URL は引数で渡すローカルの gateway
            return json.load(res)["key"]
    except urllib.error.HTTPError as e:
        # 応答本文にキーは含まれない (失敗時)
        raise SystemExit(f"キーの発行に失敗しました: HTTP {e.code} {e.read().decode()[:300]}") from None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("alias", help="キーの名前 (例: stock-analysis-agent)。Langfuse や利用額の集計に出る")
    p.add_argument("--models", default="stock-analysis,stock-analysis-next", help="許可する別名 (カンマ区切り)")
    p.add_argument("--budget", type=float, default=100.0, help="30 日あたりの上限 (USD, API 料金換算)")
    p.add_argument("--rpm", type=int, default=30, help="1 分あたりの呼び出し回数の上限")
    p.add_argument("--url", default="http://127.0.0.1:4000")
    p.add_argument("--gateway-env", type=Path, default=ROOT / "config" / "gateway.env")
    p.add_argument("--env-file", type=Path, help=f"発行したキーを {ENV_KEY} として書き込むファイル")
    args = p.parse_args(argv)

    master_key = read_env(args.gateway_env).get("LITELLM_MASTER_KEY") or os.getenv("LITELLM_MASTER_KEY", "")
    if not master_key:
        raise SystemExit(f"LITELLM_MASTER_KEY が {args.gateway_env} にありません")
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    key = generate(args.url, master_key, build_request(args.alias, models, args.budget, args.rpm))

    if args.env_file:
        set_env_value(args.env_file, ENV_KEY, key)
        print(f"{args.env_file} の {ENV_KEY} に書き込みました (alias={args.alias}, models={','.join(models)})")
    else:
        print(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
