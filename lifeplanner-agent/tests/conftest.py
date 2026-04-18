import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def db_session(tmp_path, monkeypatch):
    """
    テスト毎に SQLite ファイル DB を作成し AsyncSession を提供する。
    テーブルは metadata.create_all で作成（Alembic は走らせない）。
    """
    db_url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    monkeypatch.setenv("DB_URL", db_url)

    # services.database のモジュール状態をリセット
    import importlib
    import config
    importlib.reload(config)
    from services import database as db_mod
    importlib.reload(db_mod)

    db_mod.init_engine(db_url)
    await db_mod.init_db()

    factory = db_mod.get_session_factory()
    async with factory() as session:
        yield session

    await db_mod.close_db()


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """
    テスト毎に分離された SQLite DB を持つ AsyncClient を提供する。
    app の lifespan を経由して init_db まで走らせる。
    """
    db_url = f"sqlite+aiosqlite:///{tmp_path}/api.db"
    monkeypatch.setenv("DB_URL", db_url)
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MF_CSV_DIR", str(tmp_path / "mf_csv"))
    monkeypatch.setenv("DEV_HOUSEHOLD_ID", "test-household")

    import importlib
    import config
    importlib.reload(config)
    from services import database as db_mod
    importlib.reload(db_mod)
    import main
    importlib.reload(main)

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://test"
    ) as c:
        # lifespan を手動で走らせる
        async with main.app.router.lifespan_context(main.app):
            yield c
