"""A1 CLI のテスト (パイプラインは偽物に差し替える)。"""
from __future__ import annotations

from datetime import timedelta

from typer.testing import CliRunner

from src.common.timeutil import utc_now
from src.intel import __main__ as cli


class FakePipeline:
    def __init__(self, fresh: set[str]) -> None:
        self.fresh = fresh
        self.calls: list[str] = []

    def last_success(self, source: str):
        return utc_now() - timedelta(minutes=5) if source in self.fresh else None

    def bootstrap(self) -> bool:
        self.calls.append("bootstrap")
        return True

    def run_kev(self) -> None:
        self.calls.append("kev")

    def missing_count(self) -> int:
        return 0


def test_health_reports_stale_sources(monkeypatch):
    monkeypatch.setattr(cli, "build_pipeline", lambda **_: FakePipeline({"osv", "kev", "epss", "osv_full", "reports", "extract"}))
    result = CliRunner().invoke(cli.app, ["health"])
    assert result.exit_code == 0 and "STALE" not in result.output

    monkeypatch.setattr(cli, "build_pipeline", lambda **_: FakePipeline({"osv"}))
    result = CliRunner().invoke(cli.app, ["health"])
    assert result.exit_code == 1 and "STALE kev" in result.output


def test_commands_dispatch_to_pipeline(monkeypatch):
    fake = FakePipeline(set())
    monkeypatch.setattr(cli, "build_pipeline", lambda **_: fake)
    assert "bootstrap completed" in CliRunner().invoke(cli.app, ["bootstrap"]).output
    assert CliRunner().invoke(cli.app, ["kev"]).exit_code == 0
    assert fake.calls == ["bootstrap", "kev"]


def test_schedule_uses_configured_full_refresh_interval(monkeypatch):
    monkeypatch.setattr(cli.settings, "osv_full_refresh_days", 3)
    assert cli.schedule()["osv_full"] == timedelta(days=3)
