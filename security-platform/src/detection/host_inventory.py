"""開発 PC に入っているツールの一覧 (ホストで作る: ``make detection-host``)。

本番サービスの lockfile・イメージと同じように、開発 PC で使うツールも照合する
(エディタ拡張や MCP サーバーの乗っ取り・改ざんは、入れた時点で PC の認証情報が狙われる)。
detection コンテナにホームディレクトリは見せないので、一覧はホストで作って
``data/sbom/hosts/<host_id>.json`` に置き、照合 (scan) はそのファイルを読むだけ。

集めるもの (OSV で照合できるもの):
- Claude Code 本体 (ネイティブ版。npm の @anthropic-ai/claude-code と同じ版番号)
- エディタ拡張: VS Code は Marketplace (``VSCode``)、Cursor・Windsurf・VSCodium など
  Open VSX から入れるエディタは ``VSCode:https://open-vsx.org`` として区別する
- npm のグローバル・npx のキャッシュ (実際に取得して実行したもの。依存も含む)
- uv tool・uvx の環境・pipx (依存も含む)
- MCP サーバーの設定 (~/.claude.json・Claude Desktop・roots の下の .mcp.json) の起動パッケージ。
  版を 1 つに固定しているものは部品として照合し、固定していないものはマニフェストに残す
照合できないもの (Homebrew) も一覧としては残す (エコシステム ``purl:brew``)。

読むのは各パッケージのマニフェスト (package.json・METADATA) と設定ファイルだけで、
拡張やパッケージのコードは実行しない。MCP の設定は起動コマンドとパッケージ名だけを読み、
env やそれ以外の引数 (トークンや接続文字列が入る) は残さない。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess  # nosec B404  npm・brew を引数リストで呼ぶだけ (シェルは使わない)
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..common.timeutil import utc_now_iso
from .lockfiles import (
    Component,
    ParsedLockfile,
    _npm_purl,
    _pypi_purl,
    canonical_pypi_name,
)
from .versions import OPEN_VSX, VSCODE

logger = logging.getLogger(__name__)

FORMAT = "security-platform/host-inventory@1"
CLAUDE_CODE_NPM = "@anthropic-ai/claude-code"
COMMAND_TIMEOUT = 120
MCP_SEARCH_DEPTH = 4  # roots から .mcp.json を探す深さ
SKIP_DIRS = frozenset({"node_modules", ".git", ".venv", "venv", "__pycache__", ".terraform", "dist", "build"})

# ホームからの拡張フォルダ → 拡張を入れるマーケットプレイス (OSV のエコシステム)
EDITOR_EXTENSION_DIRS = {
    ".vscode/extensions": VSCODE,
    ".vscode-insiders/extensions": VSCODE,
    ".cursor/extensions": OPEN_VSX,
    ".windsurf/extensions": OPEN_VSX,
    ".vscode-oss/extensions": OPEN_VSX,  # VSCodium
    ".kiro/extensions": OPEN_VSX,
    ".antigravity/extensions": OPEN_VSX,
}
# Python のツール環境 (ホームから。<dir>/<環境>/lib/python*/site-packages)
PYTHON_TOOL_DIRS = {
    ".local/share/uv/tools": "uv-tool",
    ".cache/uv/environments-v2": "uvx",
    ".local/pipx/venvs": "pipx",
    ".local/share/pipx/venvs": "pipx",
}
NPM_RUNNERS = frozenset({"npx", "bunx"})
PYPI_RUNNERS = frozenset({"uvx"})
_HOST_ID = re.compile(r"[^a-z0-9-]+")
_EXACT_NPM = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
_EXACT_PYPI = re.compile(r"^\d+(?:\.\d+)*(?:(?:a|b|rc|\.post|\.dev)\d+)*$")

# (argv) → 標準出力。テストでは差し替える
Runner = Callable[[list[str]], str]


@dataclass(frozen=True)
class HostComponent:
    ecosystem: str
    name: str
    version: str
    source: str  # どこで見つけたか (例: "vscode", "npx-cache", "claude-code")
    direct: bool = True  # 自分で入れたもの (依存として入ったものは False)


@dataclass(frozen=True)
class McpServer:
    config: str  # 設定ファイル (~ からの相対)
    name: str
    runner: str
    ecosystem: str
    package: str
    version: str | None  # 指定された版 (無ければ None)
    pinned: bool  # 版を 1 つに固定しているか (latest・範囲指定・指定なしは False)


@dataclass
class Inventory:
    host: str
    generated_at: str
    components: list[HostComponent] = field(default_factory=list)
    mcp_servers: list[McpServer] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        unique: dict[tuple[str, str, str], HostComponent] = {}
        for c in self.components:
            key = (c.ecosystem, c.name, c.version)
            prev = unique.get(key)
            if prev is None or (c.direct and not prev.direct):
                unique[key] = c
        comps = sorted(unique.values(), key=lambda c: (c.ecosystem, c.name.lower(), c.version))
        return json.dumps({
            "format": FORMAT, "host": self.host, "generated_at": self.generated_at,
            "components": [asdict(c) for c in comps],
            "mcp_servers": [asdict(m) for m in self.mcp_servers], "errors": self.errors,
        }, ensure_ascii=False, indent=1)


def default_host_id() -> str:
    name = socket.gethostname().lower().removesuffix(".local")
    return _HOST_ID.sub("-", name).strip("-") or "localhost"


def run_command(argv: list[str]) -> str:
    env = {**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_ANALYTICS": "1"}
    done = subprocess.run(  # nosec B603  argv は固定のコマンド
        argv, env=env, capture_output=True, text=True, timeout=COMMAND_TIMEOUT, check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(argv[:2])} が失敗しました: {done.stderr.strip()[-300:]}")
    return done.stdout


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _rel(path: Path, home: Path) -> str:
    try:
        return f"~/{path.relative_to(home)}"
    except ValueError:
        return str(path)


def _name_version(pkg: Any) -> tuple[str, str] | None:
    if isinstance(pkg, dict) and isinstance(pkg.get("name"), str) and isinstance(pkg.get("version"), str):
        return pkg["name"], pkg["version"]
    return None


# ── Claude Code ─────────────────────────────────────────────────────────────
def claude_code(home: Path) -> list[HostComponent]:
    """ネイティブ版は ~/.local/share/claude/versions/<版>。使っているのは ~/.local/bin/claude のリンク先。

    古い版はファイルが残っていても起動されないので数えない (過去に使った版は照合の履歴で追う)。
    """
    versions_dir = home / ".local/share/claude/versions"
    if not versions_dir.is_dir():
        return []
    try:
        active = (home / ".local/bin/claude").resolve(strict=True)
    except OSError:
        active = None
    if active is not None and active.parent == versions_dir.resolve():
        names = [active.name]
    else:
        names = sorted(p.name for p in versions_dir.iterdir() if not p.name.startswith("."))
    return [HostComponent("npm", CLAUDE_CODE_NPM, v, "claude-code") for v in names]


# ── エディタ拡張 ────────────────────────────────────────────────────────────
def editor_extensions(home: Path) -> list[HostComponent]:
    out = []
    for rel, ecosystem in EDITOR_EXTENSION_DIRS.items():
        root = home / rel
        if not root.is_dir():
            continue
        obsolete = _read_json(root / ".obsolete") or {}  # アンインストール済み (次の起動で消える)
        editor = rel.split("/", 1)[0].lstrip(".")
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name.startswith(".") or d.name in obsolete:
                continue
            pkg = _read_json(d / "package.json")
            nv = _name_version(pkg)
            publisher = pkg.get("publisher") if isinstance(pkg, dict) else None
            if nv and isinstance(publisher, str) and publisher:
                out.append(HostComponent(ecosystem, f"{publisher}.{nv[0]}", nv[1], editor))
    return out


# ── npm ─────────────────────────────────────────────────────────────────────
def _package_dirs(node_modules: Path) -> Iterator[Path]:
    """node_modules 直下のパッケージ (@scope/name を含む)。シンボリックリンク (npm link) はたどらない。"""
    if not node_modules.is_dir():
        return
    for d in sorted(node_modules.iterdir()):
        if d.is_symlink() or not d.is_dir() or d.name.startswith("."):
            continue
        if d.name.startswith("@"):
            yield from (s for s in sorted(d.iterdir()) if s.is_dir() and not s.is_symlink())
        else:
            yield d


def npm_packages(node_modules: Path, source: str, direct: set[str] | None = None) -> list[HostComponent]:
    """node_modules の下を入れ子までたどる。direct が None なら最上位を自分で入れたものとみなす。"""
    out = []
    for pkg_dir in _package_dirs(node_modules):
        nv = _name_version(_read_json(pkg_dir / "package.json"))
        if nv:
            is_direct = nv[0] in direct if direct is not None else True
            out.append(HostComponent("npm", nv[0], nv[1], source, is_direct))
        out += npm_packages(pkg_dir / "node_modules", source, set())
    return out


def npm_global(home: Path, run: Runner) -> list[HostComponent]:
    roots = {p for p in (home / ".nvm/versions/node").glob("*/lib/node_modules")}
    if shutil.which("npm"):
        roots.add(Path(run(["npm", "root", "-g"]).strip()))
    out = []
    for root in sorted(roots):
        out += npm_packages(root, "npm-global")
    return out


def npx_cache(home: Path) -> list[HostComponent]:
    """npx が取得したパッケージ (~/.npm/_npx/<hash>/)。要求したものは package.json の dependencies。"""
    out = []
    base = home / ".npm/_npx"
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        manifest = _read_json(d / "package.json")
        deps = manifest.get("dependencies") if isinstance(manifest, dict) else None
        out += npm_packages(d / "node_modules", "npx-cache", set(deps) if isinstance(deps, dict) else None)
    return out


# ── Python ──────────────────────────────────────────────────────────────────
def _metadata(path: Path) -> tuple[str, str] | None:
    name = version = None
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    break  # ヘッダーの終わり
                if line.startswith("Name:"):
                    name = line[5:].strip()
                elif line.startswith("Version:"):
                    version = line[8:].strip()
    except OSError:
        return None
    return (name, version) if name and version else None


def python_tools(home: Path) -> list[HostComponent]:
    out = []
    for rel, source in PYTHON_TOOL_DIRS.items():
        base = home / rel
        if not base.is_dir():
            continue
        for env in sorted(p for p in base.iterdir() if p.is_dir()):
            tool = canonical_pypi_name(env.name)
            for meta in sorted(env.glob("lib/python*/site-packages/*.dist-info/METADATA")):
                nv = _metadata(meta)
                if nv:
                    out.append(HostComponent("PyPI", nv[0], nv[1], source, canonical_pypi_name(nv[0]) == tool))
    return out


# ── MCP サーバー ────────────────────────────────────────────────────────────
def _npm_spec(spec: str) -> tuple[str, str | None]:
    at = spec.rfind("@")
    return (spec[:at], spec[at + 1:]) if at > 0 else (spec, None)


def _pypi_spec(spec: str) -> tuple[str, str | None]:
    for sep in ("==", "@"):
        if sep in spec:
            name, _, version = spec.partition(sep)
            return name.strip(), version.strip()
    return re.split(r"[<>=!~\[]", spec, maxsplit=1)[0].strip(), None


def mcp_server(config: str, name: str, server: Any) -> McpServer | None:
    """起動コマンドからパッケージを読む。npx・bunx・uvx 以外 (http・ローカルのスクリプト) は対象外。"""
    if not isinstance(server, dict) or not isinstance(server.get("command"), str):
        return None
    runner = Path(server["command"]).name
    args = [a for a in server.get("args") or [] if isinstance(a, str)]
    if runner in PYPI_RUNNERS and "--from" in args:
        i = args.index("--from")
        spec = args[i + 1] if i + 1 < len(args) else None
    else:
        spec = next((a for a in args if not a.startswith("-")), None)
    if not spec:
        return None
    if runner in NPM_RUNNERS:
        package, version = _npm_spec(spec)
        pinned = bool(version and _EXACT_NPM.match(version))
        return McpServer(config, name, runner, "npm", package, version, pinned)
    if runner in PYPI_RUNNERS:
        package, version = _pypi_spec(spec)
        pinned = bool(version and _EXACT_PYPI.match(version))
        return McpServer(config, name, runner, "PyPI", package, version, pinned)
    return None


def _servers_in(data: Any) -> Iterator[tuple[str, Any]]:
    if not isinstance(data, dict):
        return
    if isinstance(data.get("mcpServers"), dict):
        yield from data["mcpServers"].items()
    for project in (data.get("projects") or {}).values() if isinstance(data.get("projects"), dict) else ():
        if isinstance(project, dict) and isinstance(project.get("mcpServers"), dict):
            yield from project["mcpServers"].items()


def _find_mcp_json(root: Path) -> Iterator[Path]:
    base_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        too_deep = len(Path(dirpath).parts) - base_depth >= MCP_SEARCH_DEPTH
        dirnames[:] = [] if too_deep else sorted(d for d in dirnames if d not in SKIP_DIRS)
        if ".mcp.json" in filenames:
            yield Path(dirpath) / ".mcp.json"


def mcp_servers(home: Path, roots: list[Path]) -> list[McpServer]:
    files = [home / ".claude.json", home / "Library/Application Support/Claude/claude_desktop_config.json",
             home / ".cursor/mcp.json", home / ".codeium/windsurf/mcp_config.json"]
    for root in roots:
        if root.is_dir():
            files += list(_find_mcp_json(root))
    out = []
    for path in files:
        data = _read_json(path)
        for name, server in _servers_in(data):
            if (m := mcp_server(_rel(path, home), str(name), server)) is not None:
                out.append(m)
    return out


# ── Homebrew ────────────────────────────────────────────────────────────────
def homebrew(run: Runner) -> list[HostComponent]:
    if not shutil.which("brew"):
        return []
    data = json.loads(run(["brew", "info", "--json=v2", "--installed"]))
    out = []
    for f in data.get("formulae") or []:
        installed = f.get("installed") or []
        if installed and isinstance(installed[-1].get("version"), str):
            out.append(HostComponent("purl:brew", f["name"], installed[-1]["version"], "homebrew"))
    for c in data.get("casks") or []:
        if isinstance(c.get("installed"), str):
            out.append(HostComponent("purl:brew", f"cask/{c['token']}", c["installed"], "homebrew"))
    return out


# ── まとめ ──────────────────────────────────────────────────────────────────
def collect(host: str, home: Path, roots: list[Path], run: Runner = run_command) -> Inventory:
    """集められなかったものは errors に残して続ける (1 つの失敗で一覧全体を止めない)。"""
    inv = Inventory(host, utc_now_iso())
    steps: list[tuple[str, Callable[[], list[HostComponent]]]] = [
        ("claude-code", lambda: claude_code(home)),
        ("editor-extensions", lambda: editor_extensions(home)),
        ("npm-global", lambda: npm_global(home, run)),
        ("npx-cache", lambda: npx_cache(home)),
        ("python-tools", lambda: python_tools(home)),
        ("homebrew", lambda: homebrew(run)),
    ]
    for label, step in steps:
        try:
            inv.components += step()
        except Exception as e:  # noqa: BLE001  どの失敗でも他の収集は続ける
            logger.warning("%s を集められません: %s", label, e)
            inv.errors.append(f"{label}: {type(e).__name__}: {e}"[:300])
    try:
        inv.mcp_servers = mcp_servers(home, roots)
    except Exception as e:  # noqa: BLE001
        inv.errors.append(f"mcp-servers: {type(e).__name__}: {e}"[:300])
    for m in inv.mcp_servers:
        if m.pinned and m.version:
            inv.components.append(HostComponent(m.ecosystem, m.package, m.version, f"mcp:{m.name}"))
    return inv


def manifest_path(hosts_dir: Path, host: str) -> Path:
    return hosts_dir / f"{host}.json"


def write_inventory(hosts_dir: Path, inv: Inventory) -> Path:
    path = manifest_path(hosts_dir, inv.host)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(inv.to_json(), encoding="utf-8")
    os.chmod(tmp, 0o600)  # 開発 PC のツール一覧は攻撃の手がかりになるので本人だけが読める
    tmp.replace(path)
    return path


# ── 照合側 (detection コンテナ) ──────────────────────────────────────────────
class InvalidInventory(ValueError):
    pass


def read_inventory(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise InvalidInventory(f"{path.name} を読めません ({e})") from e
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("components"), list):
        raise InvalidInventory(f"{path.name} の形式が違います")
    if not isinstance(data.get("host"), str) or _HOST_ID.sub("", data["host"]) != data["host"]:
        raise InvalidInventory(f"{path.name} のホスト名が不正です")
    return data


def list_inventories(hosts_dir: Path) -> list[Path]:
    return sorted(p for p in hosts_dir.glob("*.json") if not p.name.startswith(".")) if hosts_dir.is_dir() else []


def host_purl(ecosystem: str, name: str, version: str) -> str:
    if ecosystem == "npm":
        return _npm_purl(name, version)
    if ecosystem == "PyPI":
        return _pypi_purl(name, version)
    if ecosystem in (VSCODE, OPEN_VSX):
        publisher, _, ext = name.partition(".")
        purl = f"pkg:vscode-extension/{quote(publisher, safe='')}/{quote(ext, safe='')}@{quote(version, safe='')}"
        return purl + ("?repository_url=open-vsx.org" if ecosystem == OPEN_VSX else "")
    return f"pkg:{ecosystem.removeprefix('purl:')}/{quote(name, safe='/')}@{quote(version, safe='')}"


def to_components(data: dict[str, Any]) -> list[Component]:
    out: dict[str, Component] = {}
    for c in data["components"]:
        if not isinstance(c, dict):
            continue
        eco, name, version = c.get("ecosystem"), c.get("name"), c.get("version")
        if not all(isinstance(v, str) and v for v in (eco, name, version)):
            continue
        if eco == "PyPI":
            name = canonical_pypi_name(name)
        purl = host_purl(eco, name, version)
        prev = out.get(purl)
        direct = bool(c.get("direct", True)) or (prev is not None and prev.is_direct)
        out[purl] = Component(eco, name, version, purl, direct, "runtime")
    return sorted(out.values(), key=lambda c: c.purl)


def parsed(display: str, components: list[Component], kind: str) -> ParsedLockfile:
    digest = hashlib.sha256("\n".join(c.purl for c in components).encode()).hexdigest()
    return ParsedLockfile(display, digest, tuple(components), kind=kind, subject=f"sha256:{digest}")
