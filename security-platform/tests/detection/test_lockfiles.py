"""lockfile の読み取りのテスト。"""
from __future__ import annotations

import json

import pytest

from src.detection.lockfiles import (
    UnsupportedLockfile,
    parse_package_lock,
    parse_uv_lock,
)

UV_LOCK = '''
version = 1
revision = 3

[[package]]
name = "my-app"
version = "0.1.0"
source = { editable = "." }
dependencies = [{ name = "fastapi" }, { name = "llm-client" }]

[package.optional-dependencies]
vertex = [{ name = "Google_Auth" }]

[package.dev-dependencies]
dev = [{ name = "pytest" }, { name = "requests" }]

[[package]]
name = "llm-client"
version = "0.1.0"
source = { editable = "../llm-client" }
dependencies = [{ name = "httpx" }]

[package.dev-dependencies]
dev = [{ name = "ruff" }]

[[package]]
name = "fastapi"
version = "0.120.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "starlette" }]

[[package]]
name = "starlette"
version = "0.48.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "httpx"
version = "0.28.1"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "requests" }]

[[package]]
name = "google-auth"
version = "2.40.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "pytest"
version = "8.4.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "requests"
version = "2.32.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "ruff"
version = "0.14.0"
source = { registry = "https://pypi.org/simple" }
'''


def test_uv_lock_scope_and_direct():
    comps = {c.name: c for c in parse_uv_lock(UV_LOCK)}
    assert set(comps) == {"fastapi", "starlette", "httpx", "google-auth", "pytest", "requests"}
    assert (comps["fastapi"].scope, comps["fastapi"].is_direct) == ("runtime", True)
    assert (comps["starlette"].scope, comps["starlette"].is_direct) == ("runtime", False)
    assert comps["google-auth"].purl == "pkg:pypi/google-auth@2.40.0"  # extra も runtime
    assert comps["pytest"].scope == "dev"
    # dev にも書いてあるが、パス依存 (llm-client → httpx) 経由で本番に入る
    assert (comps["requests"].scope, comps["requests"].is_direct) == ("runtime", True)


def test_package_lock_v3():
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "front", "dependencies": {"next": "15.1.0"}, "devDependencies": {"eslint": "^9"}},
            "node_modules/next": {"version": "15.1.0"},
            "node_modules/@next/env": {"version": "15.1.0"},
            "node_modules/eslint": {"version": "9.1.0", "dev": True},
            "node_modules/eslint/node_modules/semver": {"version": "6.3.1", "dev": True},
            "node_modules/semver": {"version": "7.6.0"},
            "node_modules/local": {"resolved": "../local", "link": True},
        },
    }
    comps = {c.purl: c for c in parse_package_lock(json.dumps(lock))}
    assert set(comps) == {
        "pkg:npm/next@15.1.0", "pkg:npm/%40next/env@15.1.0", "pkg:npm/eslint@9.1.0",
        "pkg:npm/semver@6.3.1", "pkg:npm/semver@7.6.0",
    }
    assert comps["pkg:npm/next@15.1.0"].is_direct and comps["pkg:npm/next@15.1.0"].scope == "runtime"
    assert comps["pkg:npm/eslint@9.1.0"].scope == "dev"
    assert not comps["pkg:npm/semver@6.3.1"].is_direct


def test_package_lock_v1_is_rejected():
    with pytest.raises(UnsupportedLockfile):
        parse_package_lock(json.dumps({"lockfileVersion": 1, "dependencies": {}}))
