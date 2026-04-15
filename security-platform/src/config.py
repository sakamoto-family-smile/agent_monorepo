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
    anthropic_api_key: str = ""        # Anthropic API key (ANTHROPIC_API_KEY)
    anthropic_auth_token: str = ""     # Bearer token for LLM proxy/gateway (ANTHROPIC_AUTH_TOKEN)
    claude_code_oauth_token: str = ""  # Long-lived OAuth token from `claude setup-token` (CLAUDE_CODE_OAUTH_TOKEN)
    gemini_api_key: str = ""
    llm_provider: str = ""  # "claude" | "gemini" | "" (auto-detect)

    # Notifications
    slack_webhook_url: str = ""
    line_notify_token: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notification_email: str = ""

    # Server settings
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8000
    proxy_host: str = "0.0.0.0"
    proxy_port: int = 8080


settings = Settings()
