"""LINE の Webhook URL の確認・切替・疎通テスト (PROPOSAL-0013 の cutover 用)。

    uv run python -m ops.line_webhook get
    uv run python -m ops.line_webhook set https://stock-analysis.<tailnet>.ts.net/api/line/webhook
    uv run python -m ops.line_webhook test

チャネルアクセストークンは `--env-file` (既定 config/local.env) の LINE_CHANNEL_ACCESS_TOKEN か、
同名の環境変数から読む。トークンは表示しない。
LINE Messaging API: GET/PUT /v2/bot/channel/webhook/endpoint, POST /v2/bot/channel/webhook/test
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

API_BASE = "https://api.line.me/v2/bot/channel/webhook"
TIMEOUT_SECONDS = 30.0  # test は LINE が実際に webhook を叩くので少し長め
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / "config" / "local.env"
TOKEN_KEY = "LINE_CHANNEL_ACCESS_TOKEN"


class WebhookError(RuntimeError):
    pass


@dataclass(frozen=True)
class Endpoint:
    url: str
    active: bool


@dataclass(frozen=True)
class TestResult:
    success: bool
    status_code: int | None
    reason: str
    detail: str


def read_env_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() == key:
            return value.strip()
    return ""


def resolve_token(env_file: Path) -> str:
    token = os.getenv(TOKEN_KEY) or read_env_value(env_file, TOKEN_KEY)
    if not token:
        raise WebhookError(f"{TOKEN_KEY} がありません ({env_file} か環境変数に設定してください)")
    return token


def validate_endpoint(url: str) -> str:
    if not url.startswith("https://"):
        raise WebhookError(f"Webhook URL は https:// で始まる必要があります: {url}")
    if not url.rstrip("/").endswith("/api/line/webhook"):
        raise WebhookError(f"Webhook URL は /api/line/webhook で終わる必要があります: {url}")
    return url.rstrip("/")


class WebhookClient:
    def __init__(self, token: str, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._headers = {"Authorization": f"Bearer {token}"}

    def _check(self, resp: httpx.Response) -> dict:
        if resp.status_code >= 400:
            # 応答本文にトークンは含まれないが、長い本文は切り詰める
            raise WebhookError(f"LINE API エラー HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    def get(self) -> Endpoint:
        data = self._check(self._client.get(f"{API_BASE}/endpoint", headers=self._headers))
        return Endpoint(url=data.get("endpoint", ""), active=bool(data.get("active")))

    def set(self, url: str) -> None:
        self._check(
            self._client.put(f"{API_BASE}/endpoint", headers=self._headers, json={"endpoint": validate_endpoint(url)})
        )

    def test(self, url: str | None = None) -> TestResult:
        body = {"endpoint": validate_endpoint(url)} if url else {}
        data = self._check(self._client.post(f"{API_BASE}/test", headers=self._headers, json=body))
        return TestResult(
            success=bool(data.get("success")),
            status_code=data.get("statusCode"),
            reason=str(data.get("reason", "")),
            detail=str(data.get("detail", "")),
        )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LINE の Webhook URL を確認・切替・テストする")
    p.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("get", help="今の Webhook URL を表示する")
    s = sub.add_parser("set", help="Webhook URL を切り替えて疎通テストする")
    s.add_argument("url")
    t = sub.add_parser("test", help="Webhook の疎通テスト (URL 省略時は今の設定先)")
    t.add_argument("url", nargs="?")
    return p.parse_args(argv)


def _print_test(result: TestResult) -> None:
    status = "OK" if result.success else "NG"
    print(f"疎通テスト {status}: HTTP {result.status_code} {result.reason} {result.detail}".rstrip())


def main(argv: list[str] | None = None, *, client: httpx.Client | None = None) -> int:
    args = _parse_args(argv)
    try:
        wc = WebhookClient(resolve_token(args.env_file), client=client)
        if args.command == "get":
            ep = wc.get()
            print(f"{ep.url} ({'有効' if ep.active else '無効'})")
            return 0
        if args.command == "set":
            before = wc.get()
            wc.set(args.url)
            print(f"Webhook URL を切り替えました: {before.url or '(未設定)'} → {validate_endpoint(args.url)}")
        result = wc.test(getattr(args, "url", None))
        _print_test(result)
        return 0 if result.success else 1
    except (WebhookError, httpx.HTTPError) as e:
        print(f"失敗: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
