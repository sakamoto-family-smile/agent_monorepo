import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parents[1]


class Settings:
    app_env: str = os.getenv("APP_ENV", "local")
    log_level: str = os.getenv("LOG_LEVEL", "info")

    # Claude (agent モード時のみ必須)
    claude_code_oauth_token: str = os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "")
    vertex_ai_project: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    vertex_ai_location: str = os.getenv("VERTEX_AI_LOCATION", "us-east5")

    # データパス
    db_path: str = os.getenv("DB_PATH", str(_REPO_ROOT / "data" / "local" / "hotcook.db"))
    data_dir: str = os.getenv("DATA_DIR", str(_REPO_ROOT / "data"))
    menu_catalog_path: str = os.getenv(
        "MENU_CATALOG_PATH",
        str(_REPO_ROOT / "data" / "skills" / "hotcook-recipes" / "menu-catalog.json"),
    )
    skills_dir: str = os.getenv("SKILLS_DIR", str(_REPO_ROOT / "data" / "skills"))

    # ── 分析基盤 (analytics-platform) 連携 ──
    analytics_enabled: bool = os.getenv("ANALYTICS_ENABLED", "true").lower() == "true"
    analytics_data_dir: str = os.getenv(
        "ANALYTICS_DATA_DIR", str(_REPO_ROOT / "data" / "analytics")
    )
    analytics_service_name: str = os.getenv("ANALYTICS_SERVICE_NAME", "hotcook-agent")
    analytics_compress: bool = os.getenv("ANALYTICS_COMPRESS", "false").lower() == "true"
    analytics_content_inline_threshold_bytes: int = int(
        os.getenv("ANALYTICS_CONTENT_INLINE_THRESHOLD_BYTES", "8192")
    )
    otel_exporter_otlp_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    otel_exporter_otlp_headers: str = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")
    otel_sampling_ratio: float = float(os.getenv("OTEL_SAMPLING_RATIO", "1.0"))
    service_version: str = os.getenv("SERVICE_VERSION", "0.1.0")

    @property
    def cors_origins(self) -> list[str]:
        if self.app_env == "local":
            return ["http://localhost:3000", "http://127.0.0.1:3000"]
        return [os.getenv("FRONTEND_URL", "")]


settings = Settings()
