"""自動改修のテストの部品。パッケージ名は架空のもの (example*) だけを使う。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import Engine, text

from src.common.db import make_engine
from src.common.migrate import upgrade
from src.common.paths import DataPaths

REGISTRY = "https://pypi.org/simple"


def _hash(*parts: str) -> str:
    return "sha256:" + hashlib.sha256("\n".join(parts).encode()).hexdigest()


def entry(name: str, version: str, *, deps: tuple[str, ...] = (), host: str = "files.pythonhosted.org",
          registry: str = REGISTRY, salt: str = "") -> str:
    lines = ["[[package]]", f'name = "{name}"', f'version = "{version}"', f'source = {{ registry = "{registry}" }}']
    if deps:
        lines.append("dependencies = [")
        lines += [f'    {{ name = "{d}" }},' for d in deps]
        lines.append("]")
    lines.append(f'sdist = {{ url = "https://{host}/packages/{name}-{version}.tar.gz", '
                 f'hash = "{_hash(name, version, "sdist", salt)}", size = 10 }}')
    lines.append("wheels = [")
    lines.append(f'    {{ url = "https://{host}/packages/{name}-{version}-py3-none-any.whl", '
                 f'hash = "{_hash(name, version, "wheel", salt)}", size = 10 }},')
    lines.append("]")
    return "\n".join(lines)


def lock(packages: dict[str, str], *, project: str = "examplesvc", entries: dict[str, str] | None = None,
         revision: int = 3, direct: tuple[str, ...] | None = None) -> str:
    """packages: 名前 → 版。direct はプロジェクトの直接の依存 (省略時は全部)。entries でエントリを差し替える。"""
    head = f'version = 1\nrevision = {revision}\nrequires-python = ">=3.12"\n'
    root = ["[[package]]", f'name = "{project}"', 'version = "0.1.0"', 'source = { virtual = "." }',
            "dependencies = ["] + [f'    {{ name = "{n}" }},' for n in sorted(direct or packages)] + ["]"]
    body = ["\n".join(root)]
    for name in sorted(packages):
        body.append((entries or {}).get(name) or entry(name, packages[name]))
    return head + "\n" + "\n\n".join(body) + "\n"


def detection_db(paths: DataPaths) -> Engine:
    upgrade("detection", paths)
    return make_engine(paths.sqlite_path("detection"))


def add_finding(engine: Engine, finding_id: str, service: str, package: str, version: str, fixed: str | None,
                *, priority: str = "P2", source_kind: str = "source", lockfile: str | None = None,
                ecosystem: str = "PyPI", state: str = "open", advisory: str | None = None) -> None:
    ev = {"ecosystem": ecosystem, "package": package, "version": version, "source_kind": source_kind,
          "source": lockfile or f"{service}/uv.lock", "kind": "vulnerable"}
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO findings (finding_id, service_id, advisory_id, purl, dependency_path, trigger, priority, "
            "fix_type, fixed_version, state, evidence_json, first_seen_at, updated_at) VALUES (:f, :s, :a, :p, "
            "'direct', 'scan', :prio, :ft, :fixed, :state, :ev, '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z')"
        ), {"f": finding_id, "s": service, "a": advisory or f"EXAMPLE-{finding_id}",
            "p": f"pkg:pypi/{package}@{version}", "prio": priority, "ft": "upgrade" if fixed else "none",
            "fixed": fixed, "state": state, "ev": json.dumps(ev)})


def write_repo(root: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)


SERVICES_YAML = """services:
  - id: examplesvc
    path: examplesvc/
    exposure: external
    deployed: true
    lockfiles: [uv.lock]
    auto_remediation: true
  - id: otherexample
    path: otherexample/
    exposure: none
    deployed: false
    lockfiles: [uv.lock]
    auto_remediation: false
"""

PYPROJECT = """[project]
name = "examplesvc"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["examplelib", "samplehttp"]

[tool.uv.sources]
examplecommon = { path = "../examplecommon" }
"""
