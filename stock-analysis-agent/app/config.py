import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    app_env: str = os.getenv("APP_ENV", "local")
    log_level: str = os.getenv("LOG_LEVEL", "info")
    claude_code_oauth_token: str = os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "")

    # Database
    db_path: str = os.getenv("DB_PATH", "data/stock_analysis.db")

    # Data directories
    data_dir: str = os.getenv("DATA_DIR", "data")
    charts_dir: str = os.getenv("CHARTS_DIR", "data/charts")
    reports_dir: str = os.getenv("REPORTS_DIR", "data/reports")
    cache_dir: str = os.getenv("CACHE_DIR", "data/cache")
    dictionaries_dir: str = os.getenv("DICTIONARIES_DIR", "data/dictionaries")

    # Security Platform MCP Proxy URL (empty = direct MCP)
    mcp_proxy_url: str = os.getenv("MCP_PROXY_URL", "")

    # Cache settings
    price_cache_ttl_hours: int = int(os.getenv("PRICE_CACHE_TTL_HOURS", "24"))

    # Finnhub（未設定の場合はJSONユニバースのみを使用）
    finnhub_api_key: str = os.getenv("FINNHUB_API_KEY", "")

    # VertexAI settings
    vertex_ai_project: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    vertex_ai_location: str = os.getenv("VERTEX_AI_LOCATION", "us-east5")

    @property
    def cors_origins(self):
        if self.app_env == "local":
            return ["http://localhost:3000", "http://127.0.0.1:3000"]
        return [os.getenv("FRONTEND_URL", "")]


settings = Settings()
