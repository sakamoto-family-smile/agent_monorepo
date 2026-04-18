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
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    # Phase 3a: LLM アドバイザー設定
    llm_model: str = os.getenv("LLM_MODEL", "claude-sonnet-4-6")
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "1200"))
    # LLM 呼出をモック化(テスト・オフライン時)
    llm_mock_mode: bool = os.getenv("LLM_MOCK_MODE", "false").lower() == "true"

    # Phase 1+ DB 接続
    db_url: str = os.getenv("DB_URL", "sqlite+aiosqlite:///data/lifeplanner.db")

    # 認証スタブ（Phase 1 開発用、Phase 3 で Firebase Auth へ移行）
    dev_household_id: str = os.getenv("DEV_HOUSEHOLD_ID", "dev-household-00000000")

    @property
    def cors_origins(self) -> list[str]:
        if self.app_env == "local":
            return ["http://localhost:3000", "http://127.0.0.1:3000"]
        frontend = os.getenv("FRONTEND_URL", "")
        return [frontend] if frontend else []


settings = Settings()
