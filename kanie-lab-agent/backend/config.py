import os
from typing import List
from dotenv import load_dotenv

load_dotenv()


class Settings:
    app_env: str = os.getenv("APP_ENV", "local")
    log_level: str = os.getenv("LOG_LEVEL", "info")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    firebase_project_id: str = os.getenv("FIREBASE_PROJECT_ID", "demo-kanie-lab")
    workspace_base: str = os.getenv("WORKSPACE_BASE", "/app/workspace/users")
    # Security Platform MCP Proxy URL (empty = bypass proxy, direct MCP)
    mcp_proxy_url: str = os.getenv("MCP_PROXY_URL", "")

    @property
    def cors_origins(self) -> List[str]:
        if self.app_env == "local":
            return ["http://localhost:3000", "http://127.0.0.1:3000"]
        return [os.getenv("FRONTEND_URL", "")]


settings = Settings()
