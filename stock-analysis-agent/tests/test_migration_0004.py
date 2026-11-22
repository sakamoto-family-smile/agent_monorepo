"""0004_report_evaluation が models と一致し、戻せることの確認 (PROPOSAL-0014)。"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from services.db_models import Report

import config
from alembic import command

ROOT = Path(__file__).resolve().parents[1]


def _alembic(url: str, monkeypatch) -> Config:
    monkeypatch.setattr(config.settings, "database_url", url)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    return cfg


def _report_columns(path: Path) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{path}")
    try:
        return {c["name"] for c in sa.inspect(engine).get_columns("reports")}
    finally:
        engine.dispose()


def test_upgrade_matches_model_and_downgrade_restores(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    cfg = _alembic(f"sqlite+aiosqlite:///{db}", monkeypatch)

    command.upgrade(cfg, "head")
    assert _report_columns(db) == {c.name for c in Report.__table__.columns}

    command.downgrade(cfg, "0003_watchlist")
    assert _report_columns(db) == {"id", "ticker", "company_name", "report_data", "created_at"}
