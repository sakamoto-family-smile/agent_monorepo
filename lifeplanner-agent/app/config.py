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
    # provider: "anthropic" (Anthropic API 直呼) | "vertex" (GCP Vertex AI 経由)
    llm_provider: str = os.getenv("LLM_PROVIDER", "anthropic").lower()
    llm_model: str = os.getenv("LLM_MODEL", "claude-sonnet-4-6")
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "1200"))
    # LLM 呼出をモック化(テスト・オフライン時)
    llm_mock_mode: bool = os.getenv("LLM_MOCK_MODE", "false").lower() == "true"
    # Vertex AI 用 (llm_provider=vertex のとき必須)
    # ADC (Application Default Credentials) を使用。ローカルは `gcloud auth application-default login`。
    gcp_project_id: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    vertex_region: str = os.getenv("VERTEX_AI_LOCATION", "us-east5")

    # Phase 1+ DB 接続
    db_url: str = os.getenv("DB_URL", "sqlite+aiosqlite:///data/lifeplanner.db")

    # 認証スタブ（Phase 1 開発用、Phase 3 で Firebase Auth へ移行）
    dev_household_id: str = os.getenv("DEV_HOUSEHOLD_ID", "dev-household-00000000")

    # Phase 3b: LINE Bot 連携 (未設定時は webhook が 503 を返す)
    line_channel_secret: str = os.getenv("LINE_CHANNEL_SECRET", "")
    line_channel_access_token: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    # Phase 3b.2: LIFF (LINE Front-end Framework) ID。
    # 未設定時は /liff/link.html と /api/line/liff-login が 503 を返す。
    line_liff_id: str = os.getenv("LIFF_ID", "")
    # LINE ID token 検証用の client_id (LINE Login チャネルの Channel ID)。
    # 未指定の場合 LIFF_CHANNEL_ID = LIFF_ID の prefix (hyphen 前) を使う慣習もあるが、
    # 明示できるように独立した env で受ける。
    line_login_channel_id: str = os.getenv("LINE_LOGIN_CHANNEL_ID", "")

    @property
    def cors_origins(self) -> list[str]:
        if self.app_env == "local":
            return ["http://localhost:3000", "http://127.0.0.1:3000"]
        frontend = os.getenv("FRONTEND_URL", "")
        return [frontend] if frontend else []


settings = Settings()
