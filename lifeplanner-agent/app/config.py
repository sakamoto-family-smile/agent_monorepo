import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    app_env: str = os.getenv("APP_ENV", "local")
    log_level: str = os.getenv("LOG_LEVEL", "info")

    data_dir: str = os.getenv("DATA_DIR", "data")
    mf_csv_dir: str = os.getenv("MF_CSV_DIR", "data/mf_csv")

    # Phase 3+ の拡張用（未設定でも起動可能）
    claude_code_oauth_token: str = os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "")
    brave_api_key: str = os.getenv("BRAVE_API_KEY", "")

    # Phase 1+ で DB 接続（未設定時はアプリは DB 非接続で起動）
    db_url: str = os.getenv("DB_URL", "")

    @property
    def cors_origins(self) -> list[str]:
        if self.app_env == "local":
            return ["http://localhost:3000", "http://127.0.0.1:3000"]
        frontend = os.getenv("FRONTEND_URL", "")
        return [frontend] if frontend else []


settings = Settings()
