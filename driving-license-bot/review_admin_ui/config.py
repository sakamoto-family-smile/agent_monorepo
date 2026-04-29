"""review-admin-ui の設定（pydantic-settings）。

app/config.py と分離する理由:
- review-admin-ui は LINE secret 等を必要としない（最小権限化）
- 別 Cloud Run service として deploy するため env 体系を独立させたい
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

    # --- IAP / 認可 ---
    # 開発時のみ true: IAP JWT 検証をスキップし、固定の dev email を返す
    # 本番（Cloud Run + IAP）では必ず false にする
    dev_bypass: bool = False
    dev_bypass_email: str = "dev@example.com"

    # IAP 検証時に許可する email の comma-separated list
    # 例: "operator1@example.com,operator2@example.com"
    allowed_emails: str = ""

    # IAP audience: `/projects/<NUMBER>/global/backendServices/<SERVICE_ID>`
    # Cloud Run 前段の HTTPS LB + IAP Brand から取得（C3 の TF で確定）
    iap_audience: str = ""


settings = AdminSettings()
