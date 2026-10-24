"""アプリ設定 (pydantic-settings)。

環境変数 (または .env) から読み込む。テストでは monkeypatch.setenv + importlib.reload で
`settings` を再構築する運用 (lifeplanner-agent 流儀を踏襲)。
"""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict

# ローカル開発 / テストとみなす APP_ENV の値。これ以外 (deploy_cloud_run.sh の既定
# `prod` など) は本番相当として扱う。
_LOCAL_APP_ENVS = frozenset({"dev", "local", "test"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # --- App ---
    app_env: str = "dev"
    service_version: str = "0.1.0"
    log_level: str = "INFO"

    # FastAPI の /docs・/redoc・/openapi.json を公開するか。
    # 既定 (false) では「ローカル開発 (APP_ENV が dev/local/test かつ Cloud Run 外)」
    # のときだけ公開する。本番で一時的に見たい場合のみ ENABLE_API_DOCS=true を明示する。
    enable_api_docs: bool = False

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
    # PROPOSAL-0010 P5-3: イベント送信 backend。"local" (既定) | "pubsub"。
    # pubsub のとき analytics_pubsub_topic 必須 (未設定なら local に fallback)。
    analytics_storage_backend: str = "local"
    analytics_pubsub_topic: str = ""
    analytics_gcp_project: str = ""

    # --- OTel ---
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""
    otel_sampling_ratio: float = 1.0

    # --- Upload limits ---
    upload_max_bytes: int = 5 * 1024 * 1024

    # --- Phase 1.5: 一時画像配信 ---
    # LINE ImageMessage は HTTPS の公開 URL を要求する。
    # Cloud Run の場合は `https://<service>-<...>.run.app`、
    # ローカル開発では ngrok の HTTPS URL を入れる。
    # 末尾スラッシュなし、空ならアプリは画像コマンドを reject する。
    public_base_url: str = ""

    # ImageStore 容量・TTL
    image_store_max_entries: int = 50
    image_store_ttl_seconds: int = 3600

    # --- Phase 3: Vertex AI Gemini (LLM 相談 + 自然言語分析) ---
    # 空ならコンサルティングモードを deploy しない (テキストで stub 応答)
    vertex_project: str = ""
    vertex_location: str = "asia-northeast1"
    # Gemini モデル ID。tool use 対応、prompt caching は実装側で chunk 分割。
    vertex_model: str = "gemini-2.5-pro"
    # consultation の生成パラメータ
    vertex_max_output_tokens: int = 2048
    vertex_temperature: float = 0.4
    # 1 conversation の最大 tool use ループ回数 (暴走防止)
    vertex_max_tool_iterations: int = 5
    # 1 conversation で保持する直近メッセージ数 (context window 節約)
    vertex_history_window: int = 20

    # --- Phase 3-C: リッチメニュー切替 ---
    # consulting mode に入った時に user に紐付ける rich menu の ID。
    # `scripts/setup_richmenu.py --mode consulting` で生成された ID を入れる。
    # 空なら mode 切替時に rich menu の link/unlink を行わない (default の normal
    # メニューがそのまま表示される)。
    rich_menu_id_consulting: str = ""

    @property
    def is_local_env(self) -> bool:
        """ローカル開発 / テスト環境か。

        Cloud Run は予約済み env `K_SERVICE` を必ず注入するため、APP_ENV の
        設定漏れがあっても Cloud Run 上では本番相当として扱う (fail-closed)。
        """
        if os.environ.get("K_SERVICE"):
            return False
        return self.app_env.strip().lower() in _LOCAL_APP_ENVS

    @property
    def api_docs_enabled(self) -> bool:
        return self.enable_api_docs or self.is_local_env

    @property
    def vertex_configured(self) -> bool:
        return bool(self.vertex_project)

    @property
    def family_user_id_set(self) -> frozenset[str]:
        if not self.family_user_ids:
            return frozenset()
        return frozenset(uid.strip() for uid in self.family_user_ids.split(",") if uid.strip())


settings = Settings()
