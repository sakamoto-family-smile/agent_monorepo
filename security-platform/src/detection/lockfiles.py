"""lockfile から照合用のコンポーネント一覧を作る。

- uv.lock (PyPI): ``[[package]]`` の一覧。プロジェクト自身とパス指定のローカルパッケージ
  (editable / virtual / directory / path) は照合対象にせず、依存をたどる起点・中継にだけ使う
- package-lock.json v2 / v3 (npm): ``packages`` の ``node_modules/...``。link は除く

scope は ``runtime`` (本番で読み込まれる) と ``dev`` (開発・テスト用の依存からしか届かない)。
"""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Scope = Literal["runtime", "dev"]
LOCAL_SOURCES = frozenset({"editable", "virtual", "directory", "path"})


@dataclass(frozen=True)
class Component:
    ecosystem: str
    name: str
    version: str
    purl: str
    is_direct: bool
    scope: Scope


@dataclass(frozen=True)
class ParsedLockfile:
    path: str
    sha256: str
    components: tuple[Component, ...]


class UnsupportedLockfile(ValueError):
    pass


def canonical_pypi_name(name: str) -> str:
    """PEP 503 の正規化 (大文字小文字と -_. の違いを無視する)。"""
    return re.sub(r"[-_.]+", "-", name).lower()


def _pypi_purl(name: str, version: str) -> str:
    return f"pkg:pypi/{canonical_pypi_name(name)}@{version}"


def _npm_purl(name: str, version: str) -> str:
    # スコープ付き (@scope/name) は purl で %40 にする
    return f"pkg:npm/{name.replace('@', '%40', 1) if name.startswith('@') else name}@{version}"


def _dep_names(entries: list[dict[str, Any]] | None) -> list[str]:
    return [canonical_pypi_name(d["name"]) for d in entries or [] if isinstance(d, dict) and "name" in d]


def parse_uv_lock(text: str) -> list[Component]:
    data = tomllib.loads(text)
    packages = {canonical_pypi_name(p["name"]): p for p in data.get("package") or [] if "name" in p}

    def is_local(pkg: dict[str, Any]) -> bool:
        return bool(LOCAL_SOURCES.intersection(pkg.get("source") or {}))

    def runtime_deps(pkg: dict[str, Any]) -> list[str]:
        names = _dep_names(pkg.get("dependencies"))
        for extra in (pkg.get("optional-dependencies") or {}).values():
            names += _dep_names(extra)
        return names

    def dev_deps(pkg: dict[str, Any]) -> list[str]:
        return [n for group in (pkg.get("dev-dependencies") or {}).values() for n in _dep_names(group)]

    # 自分自身 (source が ".") が起点。見つからなければローカルパッケージ全部を起点にする
    roots = [n for n, p in packages.items() if "." in (p.get("source") or {}).values()]
    roots = roots or [n for n, p in packages.items() if is_local(p)]
    direct = {d for r in roots for d in runtime_deps(packages[r]) + dev_deps(packages[r])}

    def reach(starts: list[str]) -> set[str]:
        seen: set[str] = set()
        queue = deque(starts)
        while queue:
            name = queue.popleft()
            if name in seen or name not in packages:
                continue
            seen.add(name)
            queue.extend(runtime_deps(packages[name]))
        return seen

    # パス依存の他プロジェクトは runtime_deps だけたどる (その dev 依存は自分の環境に入らない)
    runtime = reach([d for r in roots for d in runtime_deps(packages[r])])
    dev = reach([d for r in roots for d in dev_deps(packages[r])]) - runtime
    out = []
    for name in sorted(runtime | dev):
        pkg = packages[name]
        if is_local(pkg) or "version" not in pkg:
            continue
        out.append(Component(
            "PyPI", name, str(pkg["version"]), _pypi_purl(name, str(pkg["version"])),
            name in direct, "runtime" if name in runtime else "dev",
        ))
    return out


def parse_package_lock(text: str) -> list[Component]:
    data = json.loads(text)
    if int(data.get("lockfileVersion") or 0) < 2 or "packages" not in data:
        raise UnsupportedLockfile("package-lock.json v1 は未対応 (npm 7 以降で作り直す)")
    pkgs: dict[str, dict[str, Any]] = data["packages"]
    root = pkgs.get("") or {}
    direct = set(root.get("dependencies") or {}) | set(root.get("devDependencies") or {}) | set(
        root.get("optionalDependencies") or {}
    )
    seen: dict[str, Component] = {}
    for key, entry in sorted(pkgs.items()):
        if not key.startswith("node_modules/") and "/node_modules/" not in key:
            continue  # ルートやワークスペースのソース
        if entry.get("link") or not entry.get("version"):
            continue
        name = entry.get("name") or key.rsplit("node_modules/", 1)[1]
        version = str(entry["version"])
        purl = _npm_purl(name, version)
        is_direct = key == f"node_modules/{name}" and name in direct
        comp = Component("npm", name, version, purl, is_direct, "dev" if entry.get("dev") else "runtime")
        prev = seen.get(purl)
        if prev is None or (comp.scope == "runtime" and prev.scope == "dev") or comp.is_direct:
            seen[purl] = Component(
                "npm", name, version, purl, comp.is_direct or bool(prev and prev.is_direct),
                "runtime" if comp.scope == "runtime" or (prev and prev.scope == "runtime") else "dev",
            )
    return list(seen.values())


PARSERS = {"uv.lock": parse_uv_lock, "package-lock.json": parse_package_lock}


def parse_lockfile(path: Path, display_path: str) -> ParsedLockfile:
    parser = PARSERS.get(path.name)
    if parser is None:
        raise UnsupportedLockfile(f"未対応の lockfile: {path.name}")
    raw = path.read_bytes()
    return ParsedLockfile(
        display_path, hashlib.sha256(raw).hexdigest(), tuple(parser(raw.decode("utf-8")))
    )
