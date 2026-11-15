"""cutover 用ツール (ops.line_webhook / ops.secrets_sync, PROPOSAL-0013) のテスト。"""

from __future__ import annotations

import json
import stat

import httpx
import pytest
from ops import line_webhook, secrets_sync

# ---------------------------------------------------------------------------
# line_webhook
# ---------------------------------------------------------------------------


class _FakeLine:
    def __init__(self, *, test_success: bool = True) -> None:
        self.endpoint = "https://old.run.app/api/line/webhook"
        self.requests: list[tuple[str, str, dict]] = []
        self.test_success = test_success

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        self.requests.append((request.method, request.url.path, body))
        assert request.headers["Authorization"] == "Bearer TOKEN"
        if request.url.path.endswith("/endpoint") and request.method == "GET":
            return httpx.Response(200, json={"endpoint": self.endpoint, "active": True})
        if request.url.path.endswith("/endpoint") and request.method == "PUT":
            self.endpoint = body["endpoint"]
            return httpx.Response(200, json={})
        if request.url.path.endswith("/test"):
            return httpx.Response(
                200,
                json={"success": self.test_success, "statusCode": 200 if self.test_success else 502, "reason": "OK"},
            )
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / "local.env"
    path.write_text("# comment\nLINE_CHANNEL_ACCESS_TOKEN=TOKEN\nAPP_ENV=prod\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _no_token_env(monkeypatch):
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)


def test_set_switches_endpoint_and_runs_test(env_file, capsys):
    fake = _FakeLine()
    url = "https://stock-analysis.tail1234.ts.net/api/line/webhook"

    code = line_webhook.main(["--env-file", str(env_file), "set", url], client=fake.client())

    assert code == 0
    assert fake.endpoint == url
    assert [(m, p.rsplit("/", 1)[-1]) for m, p, _ in fake.requests] == [
        ("GET", "endpoint"),
        ("PUT", "endpoint"),
        ("POST", "test"),
    ]
    out = capsys.readouterr().out
    assert "old.run.app" in out and "疎通テスト OK" in out
    assert "TOKEN" not in out


def test_test_failure_returns_nonzero(env_file):
    fake = _FakeLine(test_success=False)

    assert line_webhook.main(["--env-file", str(env_file), "test"], client=fake.client()) == 1


@pytest.mark.parametrize(
    "url",
    ["http://x.ts.net/api/line/webhook", "https://x.ts.net/api/line", "https://x.ts.net/"],
)
def test_set_rejects_invalid_urls(env_file, url):
    fake = _FakeLine()

    assert line_webhook.main(["--env-file", str(env_file), "set", url], client=fake.client()) == 2
    assert all(m != "PUT" for m, _, _ in fake.requests)


def test_missing_token_is_an_error(tmp_path, capsys):
    assert line_webhook.main(["--env-file", str(tmp_path / "none.env"), "get"], client=_FakeLine().client()) == 2
    assert "LINE_CHANNEL_ACCESS_TOKEN" in capsys.readouterr().err


def test_token_from_environment_takes_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "TOKEN")

    assert line_webhook.main(["--env-file", str(tmp_path / "none.env"), "get"], client=_FakeLine().client()) == 0


def test_api_error_is_reported(env_file):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, text="invalid token")))

    assert line_webhook.main(["--env-file", str(env_file), "get"], client=client) == 2


# ---------------------------------------------------------------------------
# secrets_sync
# ---------------------------------------------------------------------------


class _FakeGcloud:
    def __init__(self, secrets: dict[str, str]) -> None:
        self.secrets = dict(secrets)
        self.added: list[tuple[str, str]] = []

    def __call__(self, args: list[str], stdin: str | None) -> str:
        if args[:3] == ["secrets", "versions", "access"]:
            name = args[args.index("--secret") + 1]
            if name not in self.secrets:
                raise secrets_sync.SyncError("NOT_FOUND")
            return self.secrets[name]
        if args[:3] == ["secrets", "versions", "add"]:
            assert stdin is not None
            self.secrets[args[3]] = stdin
            self.added.append((args[3], stdin))
            return ""
        raise AssertionError(args)


ENV = """# 秘密情報
LINE_CHANNEL_SECRET=local-secret
LINE_CHANNEL_ACCESS_TOKEN=same-token
CLAUDE_CODE_OAUTH_TOKEN=new-oauth
BRAVE_API_KEY=
EDINET_API_KEY=
APP_ENV=prod
"""


@pytest.fixture
def secrets_env(tmp_path):
    path = tmp_path / "local.env"
    path.write_text(ENV, encoding="utf-8")
    return path


@pytest.fixture
def gcloud():
    return _FakeGcloud(
        {
            "stock-analysis-line-line-channel-secret": "remote-secret",
            "stock-analysis-line-line-channel-access-token": "same-token",
            "stock-analysis-line-claude-code-oauth-token": "old-oauth",
            "stock-analysis-line-brave-api-key": "brave",
        }
    )


def test_diff_lists_key_names_only(secrets_env, gcloud, capsys):
    assert secrets_sync.main(["diff", "--env-file", str(secrets_env)], runner=gcloud) == 0

    out = capsys.readouterr().out
    assert "LINE_CHANNEL_SECRET" in out
    assert "CLAUDE_CODE_OAUTH_TOKEN" in out
    assert "BRAVE_API_KEY" in out
    assert "LINE_CHANNEL_ACCESS_TOKEN" not in out
    for value in ("remote-secret", "local-secret", "old-oauth", "new-oauth", "brave"):
        assert value not in out


def test_pull_updates_only_changed_lines_and_keeps_comments(secrets_env, gcloud):
    assert secrets_sync.main(["pull", "--env-file", str(secrets_env)], runner=gcloud) == 0

    text = secrets_env.read_text(encoding="utf-8")
    assert text.startswith("# 秘密情報\n")
    env = secrets_sync.read_env(secrets_env)
    assert env["LINE_CHANNEL_SECRET"] == "remote-secret"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "old-oauth"
    assert env["BRAVE_API_KEY"] == "brave"
    assert env["EDINET_API_KEY"] == ""  # Secret に version が無いものは触らない
    assert env["APP_ENV"] == "prod"
    assert stat.S_IMODE(secrets_env.stat().st_mode) == 0o600


def test_push_adds_versions_only_for_changed_non_empty_values(secrets_env, gcloud, capsys):
    assert secrets_sync.main(["push", "--env-file", str(secrets_env)], runner=gcloud) == 0

    assert gcloud.added == [
        ("stock-analysis-line-line-channel-secret", "local-secret"),
        ("stock-analysis-line-claude-code-oauth-token", "new-oauth"),
    ]
    out = capsys.readouterr().out
    assert "local-secret" not in out and "new-oauth" not in out


def test_missing_env_file(tmp_path, gcloud):
    assert secrets_sync.main(["diff", "--env-file", str(tmp_path / "none.env")], runner=gcloud) == 2
