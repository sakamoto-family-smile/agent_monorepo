"""アプリ設定 (pydantic-settings)。"""

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

    # --- LINE ---
    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    line_user_ids: str = ""  # CSV

    # --- LLM ---
    anthropic_api_key: str = ""
    llm_provider: str = "anthropic"       # anthropic | vertex
    llm_model: str = "claude-haiku-4-5"
    llm_model_heavy: str = "claude-sonnet-4-6"
    llm_max_tokens: int = 1024
    llm_mock_mode: bool = False
    google_cloud_project: str = ""
    vertex_region: str = "us-east5"

    # --- Pipeline ---
    pipeline_sources_path: str = "./config/sources.yaml"
    relevance_threshold: float = 5.0
    dedup_window_days: int = 30
    tech_news_db_path: str = "./data/tech_news.db"
    top_news_n: int = 5
    top_arxiv_n: int = 2

    # --- analytics-platform ---
    analytics_enabled: bool = True
    analytics_service_name: str = "tech-news-agent"
    analytics_data_dir: str = "./data/analytics"
    analytics_compress: bool = False
    analytics_content_inline_threshold_bytes: int = 8192

    # --- OTel ---
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""
    otel_sampling_ratio: float = 1.0

    @property
    def line_user_id_list(self) -> list[str]:
        if not self.line_user_ids:
            return []
        return [uid.strip() for uid in self.line_user_ids.split(",") if uid.strip()]


settings = Settings()
