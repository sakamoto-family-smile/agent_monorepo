"""開発 PC のツール一覧 (収集) と、その照合のテスト。"""
from __future__ import annotations

import json
import stat
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from src.common.db import make_engine
from src.common.timeutil import to_iso, utc_now
from src.detection import host_inventory as hi
from src.detection.pipeline import DetectionPipeline
from src.detection.versions import OPEN_VSX, VSCODE
from tests.detection.test_pipeline import HIGH, osv_rec
from tests.intel.test_pipeline import env as intel_env  # noqa: F401  (fixture)


def write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    versions = h / ".local/share/claude/versions"
    for v in ("2.1.299", "2.1.311"):
        write(versions / v, "binary")
    (h / ".local/bin").mkdir(parents=True)
    (h / ".local/bin/claude").symlink_to(versions / "2.1.311")
    # VS Code (Marketplace) と Cursor (Open VSX)。.obsolete はアンインストール済み
    write(h / ".vscode/extensions/ms-python.python-2026.1.0/package.json",
          {"publisher": "ms-python", "name": "python", "version": "2026.1.0"})
    write(h / ".cursor/extensions/anthropic.claude-code-2.1.313/package.json",
          {"publisher": "Anthropic", "name": "claude-code", "version": "2.1.313"})
    write(h / ".cursor/extensions/old.ext-1.0.0/package.json", {"publisher": "old", "name": "ext", "version": "1.0.0"})
    write(h / ".cursor/extensions/.obsolete", {"old.ext-1.0.0": True})
    # npx のキャッシュ: 要求したのは server-x、依存に helper (入れ子も)
    npx = h / ".npm/_npx/abc123"
    write(npx / "package.json", {"dependencies": {"@acme/server-x": "^1.0.0"}})
    write(npx / "node_modules/@acme/server-x/package.json", {"name": "@acme/server-x", "version": "1.2.0"})
    write(npx / "node_modules/helper/package.json", {"name": "helper", "version": "0.1.0"})
    write(npx / "node_modules/helper/node_modules/deep/package.json", {"name": "deep", "version": "3.0.0"})
    # uv tool
    write(h / ".local/share/uv/tools/ruff/lib/python3.15/site-packages/ruff-0.15.0.dist-info/METADATA",
          "Metadata-Version: 2.4\nName: ruff\nVersion: 0.15.0\n\nbody\n")
    write(h / ".local/share/uv/tools/ruff/lib/python3.15/site-packages/typing_extensions-4.15.0.dist-info/METADATA",
          "Name: typing_extensions\nVersion: 4.15.0\n")
    # MCP の設定 (env・接続文字列は残さない)
    write(h / ".claude.json", {"projects": {"/p": {"mcpServers": {
        "pinned": {"command": "npx", "args": ["-y", "@acme/pinned@1.4.2"], "env": {"TOKEN": "secret"}},
        "remote": {"type": "http", "url": "https://mcp.example/"},
    }}}})
    write(h / "dev/repo/.mcp.json", {"mcpServers": {
        "latest": {"command": "npx", "args": ["@acme/tool@latest"]},
        "db": {"command": "npx", "args": ["-y", "@acme/pg", "postgresql://user:pw@localhost/db"]},
        "py": {"command": "uvx", "args": ["--from", "mcp-server-fetch==2025.4.7", "mcp-server-fetch"]},
    }})
    write(h / "dev/repo/node_modules/x/.mcp.json", {"mcpServers": {"skip": {"command": "npx", "args": ["evil"]}}})
    write(h / "dev/a/b/c/d/e/.mcp.json", {"mcpServers": {"deep": {"command": "npx", "args": ["too-deep"]}}})
    return h


def no_commands(monkeypatch):
    monkeypatch.setattr(hi.shutil, "which", lambda _: None)


def test_collect_reads_manifests_only(home, monkeypatch, tmp_path):
    no_commands(monkeypatch)
    inv = hi.collect("mac-1", home, [home / "dev"])
    got = {(c.ecosystem, c.name, c.version, c.source, c.direct) for c in inv.components}
    assert got == {
        ("npm", "@anthropic-ai/claude-code", "2.1.311", "claude-code", True),  # 使っている版だけ
        (VSCODE, "ms-python.python", "2026.1.0", "vscode", True),
        (OPEN_VSX, "Anthropic.claude-code", "2.1.313", "cursor", True),
        ("npm", "@acme/server-x", "1.2.0", "npx-cache", True),
        ("npm", "helper", "0.1.0", "npx-cache", False),
        ("npm", "deep", "3.0.0", "npx-cache", False),
        ("PyPI", "ruff", "0.15.0", "uv-tool", True),
        ("PyPI", "typing_extensions", "4.15.0", "uv-tool", False),
        ("npm", "@acme/pinned", "1.4.2", "mcp:pinned", True),
        ("PyPI", "mcp-server-fetch", "2025.4.7", "mcp:py", True),
    }
    servers = {(m.name, m.package, m.version, m.pinned) for m in inv.mcp_servers}
    assert servers == {
        ("pinned", "@acme/pinned", "1.4.2", True), ("latest", "@acme/tool", "latest", False),
        ("db", "@acme/pg", None, False), ("py", "mcp-server-fetch", "2025.4.7", True),
    }
    path = hi.write_inventory(tmp_path / "hosts", inv)
    body = path.read_text()
    assert "secret" not in body and "postgresql" not in body and "pw@" not in body
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert hi.read_inventory(path)["host"] == "mac-1"


def test_collect_keeps_going_when_a_source_fails(home, monkeypatch):
    monkeypatch.setattr(hi.shutil, "which", lambda name: "/usr/bin/" + name)

    def run(argv: list[str]) -> str:
        if argv[0] == "brew":
            return json.dumps({"formulae": [{"name": "openssl@3", "installed": [{"version": "3.6.0"}]}],
                               "casks": [{"token": "gcloud-cli", "installed": "560.0.0"}]})
        raise RuntimeError("npm が壊れている")

    inv = hi.collect("mac-1", home, [], run)
    assert any(e.startswith("npm-global: RuntimeError") for e in inv.errors)
    assert {("purl:brew", "openssl@3", "3.6.0"), ("purl:brew", "cask/gcloud-cli", "560.0.0")} <= {
        (c.ecosystem, c.name, c.version) for c in inv.components}


def test_mcp_spec_parsing():
    def m(command: str, *args: str):
        return hi.mcp_server("~/x", "s", {"command": command, "args": list(args)})

    assert m("npx", "-y", "@scope/pkg@1.2.3").pinned
    assert not m("npx", "@scope/pkg@^1.2.3").pinned
    assert m("npx", "@scope/pkg").version is None
    assert m("/opt/homebrew/bin/npx", "pkg@2.0.0-beta.1").pinned
    assert m("uvx", "pkg==1.0").pinned and not m("uvx", "pkg>=1.0").pinned
    assert m("node", "server.js") is None and m("npx") is None


def test_inventory_validation(tmp_path):
    bad = tmp_path / "x.json"
    write(bad, {"format": hi.FORMAT, "host": "../etc", "components": []})
    with pytest.raises(hi.InvalidInventory):
        hi.read_inventory(bad)
    write(bad, {"format": "other", "host": "x", "components": []})
    with pytest.raises(hi.InvalidInventory):
        hi.read_inventory(bad)


# ── 照合 ─────────────────────────────────────────────────────────────────────
MAL_EXT = {"id": "MAL-2026-900", "modified": "2026-10-30T00:00:00Z",
           "summary": "Malicious code in Anthropic.claude-code (Open VSX)",
           "affected": [{"package": {"ecosystem": OPEN_VSX, "name": "Anthropic.claude-code"},
                         "versions": ["2.1.313"]}]}
CVE_TOOL = osv_rec("GHSA-host-0001", "CVE-2026-5001", "npm", "@acme/tool",
                   [{"introduced": "0"}, {"fixed": "2.0.0"}], HIGH)


@pytest.fixture
def host_scan(intel_env, tmp_path):  # noqa: F811
    intel, osv, _, paths = intel_env
    osv.zips["VSCode"] = [MAL_EXT]
    osv.zips["npm"].append(CVE_TOOL)
    intel.bootstrap()
    repo = tmp_path / "repo"
    repo.mkdir()

    def inventory(components: list[dict], generated_at=None) -> None:
        write(paths.sbom_hosts_dir / "mac-1.json", {
            "format": hi.FORMAT, "host": "mac-1", "generated_at": to_iso(generated_at or utc_now()),
            "components": components, "mcp_servers": [], "errors": []})

    def make() -> DetectionPipeline:
        return DetectionPipeline(make_engine(paths.sqlite_path("detection")),
                                 make_engine(paths.sqlite_path("intel"), read_only=True), paths, repo, [],
                                 host_history=timedelta(days=90))

    return make, inventory


EVIL = {"ecosystem": OPEN_VSX, "name": "anthropic.CLAUDE-code", "version": "2.1.313", "source": "cursor"}
TOOL = {"ecosystem": "npm", "name": "@acme/tool", "version": "1.0.0", "source": "npm-global"}
SAFE = {"ecosystem": OPEN_VSX, "name": "anthropic.claude-code", "version": "2.1.314", "source": "cursor"}


def findings(p: DetectionPipeline) -> dict[str, tuple]:
    with p.engine.connect() as conn:
        rows = conn.execute(text("SELECT advisory_id, service_id, priority, state, evidence_json FROM findings"))
        return {r[0]: (r[1], r[2], r[3], json.loads(r[4])["source_kind"]) for r in rows}


def test_host_findings_and_history(host_scan):
    make, inventory = host_scan
    p = make()
    inventory([EVIL, TOOL])
    r = p.run_scan()
    assert r.services == 1
    assert findings(p) == {
        "MAL-2026-900": ("host-mac-1", "P1", "open", "host"),  # 大文字小文字が違っても当たる
        "CVE-2026-5001": ("host-mac-1", "P4", "open", "host"),  # High → 開発 PC なので 1 段下げ
    }
    # 更新で消えても、悪性パッケージは過去の版として残す。消えた版の CVE は閉じる
    inventory([SAFE])
    p.run_scan()
    assert findings(p) == {
        "MAL-2026-900": ("host-mac-1", "P1", "open", "host_history"),
        "CVE-2026-5001": ("host-mac-1", "P4", "resolved", "host"),
    }


def test_host_history_window(host_scan):
    make, inventory = host_scan
    p = make()
    inventory([EVIL], generated_at=utc_now() - timedelta(days=100))
    p.run_scan()
    assert findings(p)["MAL-2026-900"][2] == "open"
    inventory([SAFE])
    p.run_scan()  # 最後に見たのが 90 日より前なので、もう照合しない
    assert findings(p)["MAL-2026-900"][2] == "resolved"


def test_unreadable_inventory_keeps_findings(host_scan):
    make, inventory = host_scan
    p = make()
    inventory([EVIL])
    p.run_scan()
    path = p.paths.sbom_hosts_dir / "mac-1.json"
    path.write_text("{broken")
    r = p.run_scan()
    assert "host-mac-1" in r.incomplete
    assert findings(p)["MAL-2026-900"][2] == "open"


def test_host_health_check(tmp_path):
    from src.notify.health import host_checks

    d = tmp_path / "hosts"
    now = utc_now()
    write(d / "fresh.json", {"format": hi.FORMAT, "host": "fresh", "generated_at": to_iso(now - timedelta(hours=1)),
                             "components": []})
    write(d / "stale.json", {"format": hi.FORMAT, "host": "stale", "generated_at": to_iso(now - timedelta(days=3)),
                             "components": []})
    got = {c.key: c.ok for c in host_checks(d, timedelta(hours=48), now)}
    assert got == {"host:fresh": True, "host:stale": False}
