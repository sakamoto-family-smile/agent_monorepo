"""運用 DB (SQLite 3 ファイル) のマイグレーション。

各 DB は ``migrations/<name>/`` に独立した Alembic 環境を持つ。
alembic.ini は使わず、ここで Config を組み立てる。

    python -m src.common.migrate            # 全 DB を head まで
    python -m src.common.migrate intel      # intel.db のみ
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from .db import make_engine
from .paths import DB_NAMES, DataPaths, default_paths

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def alembic_config(name: str, paths: DataPaths) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR / name))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{paths.sqlite_path(name)}")
    return cfg


def upgrade(name: str, paths: DataPaths | None = None) -> None:
    paths = paths or default_paths()
    paths.ensure()
    command.upgrade(alembic_config(name, paths), "head")
    # journal_mode=WAL はファイルに永続化されるので、ここで 1 回有効にしておく
    engine = make_engine(paths.sqlite_path(name))
    with engine.connect():
        pass
    engine.dispose()
    logger.info("migrated %s.db", name)


def upgrade_all(paths: DataPaths | None = None) -> None:
    for name in DB_NAMES:
        upgrade(name, paths)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = sys.argv[1:] if argv is None else argv
    targets = args or list(DB_NAMES)
    for name in targets:
        upgrade(name)


if __name__ == "__main__":
    main()
