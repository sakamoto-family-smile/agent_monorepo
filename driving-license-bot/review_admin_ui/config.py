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

import os

from pydantic import model_validator
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

    # session の最大寿命 (秒)。既定 12 時間。idle expiry は SessionMiddleware の機能なし
    # なので、cookie max_age で実質的な強制ログアウトを設定。cookie は署名のみで
    # server 側で失効できないため、漏洩時の有効期間を短く抑える。
    session_max_age_seconds: int = 12 * 3600

    # OAuth callback の絶対 URL。Cloud Run URL + /auth/callback。
    # OAuth client の Authorized redirect URIs と一致する必要がある
    oauth_redirect_url: str = ""

    # FastAPI の /docs・/redoc・/openapi.json を公開するか (env: ADMIN_ENABLE_API_DOCS)。
    # 既定 (false) ではローカル開発 (ADMIN_ENV=local かつ Cloud Run 外) のときだけ公開。
    enable_api_docs: bool = False

    @property
    def is_local_env(self) -> bool:
        """ローカル開発 / テスト環境か。

        Cloud Run は予約済み env `K_SERVICE` を必ず注入するため、ADMIN_ENV の
        設定漏れがあっても Cloud Run 上では本番相当として扱う (fail-closed)。
        """
        if os.environ.get("K_SERVICE"):
            return False
        return self.env.strip().lower() == "local"

    @property
    def api_docs_enabled(self) -> bool:
        return self.enable_api_docs or self.is_local_env

    @property
    def dev_bypass_active(self) -> bool:
        """dev_bypass が実際に有効か。本番相当では常に False (多重防御)。"""
        return self.dev_bypass and self.is_local_env

    @model_validator(mode="after")
    def _validate_production_safety(self) -> AdminSettings:
        """本番相当 (ADMIN_ENV != local または Cloud Run 上) で危険な設定なら起動を拒否する。"""
        if self.is_local_env:
            return self
        if not self.session_secret_key.strip():
            raise ValueError(
                "ADMIN_SESSION_SECRET_KEY is required outside local env "
                f"(ADMIN_ENV={self.env!r}). Refusing to start with the insecure fallback key."
            )
        if self.dev_bypass:
            raise ValueError(
                "ADMIN_DEV_BYPASS=true is not allowed outside local env "
                f"(ADMIN_ENV={self.env!r}). Refusing to start."
            )
        return self


settings = AdminSettings()
