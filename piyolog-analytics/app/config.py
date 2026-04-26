"""アプリ設定 (pydantic-settings)。

環境変数 (または .env) から読み込む。テストでは monkeypatch.setenv + importlib.reload で
`settings` を再構築する運用 (lifeplanner-agent 流儀を踏襲)。
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # --- App ---
    app_env: str = "dev"
    service_version: str = "0.1.0"
    log_level: str = "INFO"

    # --- DB ---
    # 優先: `DATABASE_URL` (SQLAlchemy URL)
    #   sqlite+aiosqlite:///./data/piyolog.db   (dev/test 既定)
    #   postgresql+asyncpg://user:pass@host:5432/dbname   (Cloud SQL prod)
    # 後方互換: `PIYOLOG_DB_PATH` だけ設定された場合は sqlite に落とす。
    database_url: str = ""
    piyolog_db_path: str = "./data/piyolog.db"

    @property
    def resolved_database_url(self) -> str:
        """`database_url` を最終的な SQLAlchemy URL に解決する。"""
        if self.database_url:
            return self.database_url
        # legacy: piyolog_db_path → sqlite+aiosqlite:///{path}
        return f"sqlite+aiosqlite:///{self.piyolog_db_path}"

    # スキーマ作成方法。`metadata_create_all` は dev/SQLite 向け、
    # 本番 Postgres は `alembic` (= 起動時 create_all をスキップ) を使う想定。
    db_auto_create: bool = True

    # --- LINE ---
    line_channel_secret: str = ""
    line_channel_access_token: str = ""

    # --- Family アクセス制御 ---
    family_user_ids: str = ""
    family_id: str = "default"
    default_child_id: str = "default"

    # --- analytics-platform ---
    analytics_enabled: bool = True
    analytics_service_name: str = "piyolog-analytics"
    analytics_data_dir: str = "./data/analytics"
    analytics_compress: bool = False
    analytics_content_inline_threshold_bytes: int = 8192

    # --- OTel ---
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""
    otel_sampling_ratio: float = 1.0

    # --- Upload limits ---
    upload_max_bytes: int = 5 * 1024 * 1024

    @property
    def family_user_id_set(self) -> frozenset[str]:
        if not self.family_user_ids:
            return frozenset()
        return frozenset(
            uid.strip() for uid in self.family_user_ids.split(",") if uid.strip()
        )


settings = Settings()
