"""review-admin-ui の設定（pydantic-settings）。

app/config.py と分離する理由:
- review-admin-ui は LINE secret 等を必要としない（最小権限化）
- 別 Cloud Run service として deploy するため env 体系を独立させたい

認証は Phase 2-C3 当初の IAP から **App-level Google OAuth + signed session cookie**
に切り替えた (個人 GCP project は組織所属が無く IAP brand 自動 provisioning が
動かないため)。Cloud Run service は allUsers invoker（パブリック）として deploy し、
本アプリ内の OAuth flow と email allowlist で認可する。
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class AdminSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="ADMIN_",
    )

    # --- App identity ---
    service_name: str = "driving-license-bot-admin"
    service_version: str = "0.1.0"
    env: str = "local"
    log_level: str = "INFO"

    # --- 認可 ---
    # 開発時のみ true: OAuth flow をスキップし、固定の dev email を返す
    # 本番（Cloud Run）では必ず false
    dev_bypass: bool = False
    dev_bypass_email: str = "dev@example.com"

    # 許可する email の comma-separated list
    # 例: "operator1@example.com,operator2@example.com"
    allowed_emails: str = ""

    # --- Google OAuth 2.0 ---
    # Web Application 種別の Client ID / Secret (Console > APIs & Services > Credentials)
    # 本番では Secret Manager 経由で env に注入される
    oauth_client_id: str = ""
    oauth_client_secret: str = ""

    # Cookie に署名する秘密鍵（32+ bytes 推奨）。Secret Manager 管理
    session_secret_key: str = ""

    # session の最大寿命 (秒)。既定 7 日。idle expiry は SessionMiddleware の機能なし
    # なので、cookie max_age で実質的な強制ログアウトを設定
    session_max_age_seconds: int = 7 * 24 * 3600

    # OAuth callback の絶対 URL。Cloud Run URL + /auth/callback。
    # OAuth client の Authorized redirect URIs と一致する必要がある
    oauth_redirect_url: str = ""


settings = AdminSettings()
