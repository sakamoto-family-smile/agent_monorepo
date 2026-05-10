"""EtlConfig (env 駆動) のテスト。"""

from __future__ import annotations

import pytest

from fujisawa_platform.etl.config import EtlConfig


class TestRequiredFields:
    def test_user_agent_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FUJISAWA_ETL_USER_AGENT", raising=False)
        with pytest.raises(ValueError, match="user_agent"):
            EtlConfig(
                db_host="127.0.0.1",
                db_user="etl_user",
                db_password="x",
                db_name="fujisawa_kb_db",
                user_agent="",
                sitemap_url="https://www.city.fujisawa.kanagawa.jp/sitemap.xml",
            )

    def test_db_password_required(self) -> None:
        with pytest.raises(ValueError, match="db_password"):
            EtlConfig(
                db_host="127.0.0.1",
                db_user="etl_user",
                db_password="",
                db_name="fujisawa_kb_db",
                user_agent="ua/0.1 (https://x)",
                sitemap_url="https://www.city.fujisawa.kanagawa.jp/sitemap.xml",
            )


class TestDefaults:
    def test_defaults(self) -> None:
        config = EtlConfig(
            db_host="127.0.0.1",
            db_user="etl_user",
            db_password="x",
            db_name="fujisawa_kb_db",
            user_agent="ua/0.1 (https://x)",
            sitemap_url="https://www.city.fujisawa.kanagawa.jp/sitemap.xml",
        )
        assert config.db_port == 5432
        assert config.embedding_dim == 768
        assert config.min_interval_sec == 3.0
        assert config.weekly_crawl_enabled is True


class TestEnvLoading:
    def test_loads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FUJISAWA_ETL_DB_HOST", "10.0.0.1")
        monkeypatch.setenv("FUJISAWA_ETL_DB_PORT", "15432")
        monkeypatch.setenv("FUJISAWA_ETL_DB_USER", "etl_user")
        monkeypatch.setenv("FUJISAWA_ETL_DB_PASSWORD", "secret")
        monkeypatch.setenv("FUJISAWA_ETL_DB_NAME", "fujisawa_kb_db")
        monkeypatch.setenv("FUJISAWA_ETL_USER_AGENT", "etl/1.0 (https://example.com)")
        monkeypatch.setenv("FUJISAWA_ETL_SITEMAP_URL", "https://example.com/sitemap.xml")
        monkeypatch.setenv("FUJISAWA_ETL_WEEKLY_CRAWL_ENABLED", "false")

        config = EtlConfig()  # type: ignore[call-arg]

        assert config.db_host == "10.0.0.1"
        assert config.db_port == 15432
        assert config.db_password == "secret"
        assert config.weekly_crawl_enabled is False
