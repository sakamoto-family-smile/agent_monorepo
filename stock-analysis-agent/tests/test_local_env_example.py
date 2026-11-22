"""config/local.env.example (ローカル本番の雛形) が意図した構成になるかの確認 (PROPOSAL-0013)。

`config.settings` は import 時に env を読む singleton なので、雛形の env を渡した
別プロセスで Settings を組み立てて、その結果を比べる。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config" / "local.env.example"

_DUMP = """
import json
import config
s = config.settings
print(json.dumps({
    "app_env": s.app_env,
    "url": s.resolved_database_url,
    "db_auto_create": s.db_auto_create,
    "tasks_enabled": s.tasks_enabled,
    "media_backend": s.media_backend,
    "image_ttl": s.image_store_ttl_seconds,
    "report_ttl": s.report_store_ttl_seconds,
    "analytics_backend": s.analytics_storage_backend,
    "edinet_cache_backend": s.edinet_cache_backend,
    "edinet_cache_root": s.edinet_cache_root,
    "edinet_code_csv_path": s.edinet_code_csv_path,
    "enable_web_api": s.enable_web_api,
    "enable_api_docs": s.enable_api_docs,
    "max_concurrency": s.analysis_max_concurrency,
    "edinet_schedule": s.edinet_schedule_enabled,
    "backup": s.backup_enabled,
    "backup_dir": s.backup_dir,
    "health": s.health_check_enabled,
    "state_path": s.scheduler_state_path,
    "llm_gateway_url": s.llm_gateway_url,
    "llm_gateway_model": s.llm_gateway_model,
    "llm_model": s.llm_model,
}))
"""


def _parse_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def _settings_from(env_vars: dict[str, str]) -> dict:
    # 呼び出し元の DB 系 env が混ざらないよう、必要なものだけを渡す
    env = {"PATH": "/usr/bin:/bin", **env_vars}
    out = subprocess.run(
        [sys.executable, "-c", _DUMP],
        cwd=ROOT / "app",
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_example_only_contains_assignments():
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            assert "=" in stripped, f"KEY=VALUE 形式でない行: {line!r}"


def test_example_leaves_secrets_empty():
    env = _parse_env(EXAMPLE)
    for key in (
        "LINE_CHANNEL_SECRET",
        "LINE_CHANNEL_ACCESS_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "BRAVE_API_KEY",
        "EDINET_API_KEY",
        "HEALTHCHECK_PING_BASE",
        "LLM_GATEWAY_KEY",
    ):
        assert env[key] == "", f"{key} は雛形では空にする"


def test_example_builds_local_production_settings():
    s = _settings_from(_parse_env(EXAMPLE))

    assert s["app_env"] == "prod"
    assert s["enable_web_api"] is False
    assert s["enable_api_docs"] is False
    assert s["url"] == "sqlite+aiosqlite:////app/var/stock_analysis.db"
    assert s["db_auto_create"] is False
    assert s["tasks_enabled"] is False
    assert s["media_backend"] == "memory"
    assert s["image_ttl"] == 86400
    assert s["report_ttl"] == 86400
    assert s["analytics_backend"] == "local"
    assert s["edinet_cache_backend"] == "local"
    assert s["edinet_cache_root"].startswith("/app/var/")
    assert s["edinet_code_csv_path"].startswith("/app/var/")
    assert s["max_concurrency"] == 2
    assert s["edinet_schedule"] is True
    assert s["backup"] is True
    assert s["backup_dir"].startswith("/app/var/")
    assert s["health"] is True
    # LLM は gateway 経由 (PROPOSAL-0014)
    assert s["llm_gateway_url"] == "http://litellm:4000"
    assert s["llm_gateway_model"] == "stock-analysis"
    assert s["llm_model"] == "claude-opus-5-5"
    assert s["state_path"].startswith("/app/var/")


def test_scheduled_jobs_are_disabled_by_default():
    """GCP (Cloud Run) では定期処理を動かさない。既定値は無効のまま。"""
    s = _settings_from({})

    assert s["edinet_schedule"] is False
    assert s["backup"] is False
    assert s["health"] is False
