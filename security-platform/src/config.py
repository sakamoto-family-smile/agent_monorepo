"""Application configuration loaded from .env and environment variables."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / "config" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR}/data/security.db"

    # API Keys
    nvd_api_key: str = ""  # Required for full NVD rate limits (50 req/30s vs 5 req/30s)
    github_token: str = ""
    anthropic_api_key: str = ""
    vertex_ai_project: str = ""   # GCP project ID for Vertex AI
    vertex_ai_location: str = "us-central1"  # Vertex AI region
    llm_provider: str = ""  # "claude" | "gemini" | "" (auto-detect)

    # Notifications
    slack_webhook_url: str = ""

    # LINE Messaging API (Bot channel) — used by src/notifier/line.py
    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    line_user_ids: str = ""  # CSV of LINE userId (recipients of push notifications)

    # LINE Notify (DEPRECATED — サービスは 2025/03/31 に終了)。
    # 後方互換のため設定自体は残し、notifier 側で deprecation 警告を出す。
    line_notify_token: str = ""

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notification_email: str = ""

    # Server settings — コンテナ / dev サーバで全 interface にバインドするのが
    # 既定値 (本番は env で上書き or リバースプロキシ前提)。bandit B104 は
    # 意図的なので nosec で明示的に抑止する。
    dashboard_host: str = "0.0.0.0"  # nosec B104
    dashboard_port: int = 8000
    proxy_host: str = "0.0.0.0"  # nosec B104
    proxy_port: int = 8080


settings = Settings()
