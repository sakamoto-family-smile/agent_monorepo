"""設定 (pydantic-settings) — env / .env から読み込み。

env 名は `env_prefix="COUPLE_ROSTER_"` + 大文字化したフィールド名。
例: `line_channel_secret` → `COUPLE_ROSTER_LINE_CHANNEL_SECRET`。

default はすべて mock / in-memory なので、env 未設定でも CI / 開発でアプリが
起動する（`fujisawa-info-bot` と同じ思想）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

StorageMode = Literal["memory", "sheets"]
OcrProvider = Literal["mock", "drive", "vision"]


class Settings(BaseSettings):
    """環境変数 / `.env` から読み込まれる設定一式。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="COUPLE_ROSTER_",
        extra="ignore",
    )

    # ── LINE Messaging API ────────────────────────────────────────────
    line_channel_secret: str = Field(default="")
    line_channel_access_token: str = Field(default="")

    # ── 認可 (夫婦 2 名のホワイトリスト) ──────────────────────────────
    # カンマ区切りの LINE user id。空なら「全員拒否」ではなく
    # `allowed_user_ids` が空集合になり、明示設定を促す（開発時は allow_all）。
    allowed_line_user_ids: str = Field(default="")
    # 開発用: True の間はホワイトリストを無視して全員許可する。
    allow_all_users: bool = Field(default=True)

    # ── ストレージ ────────────────────────────────────────────────────
    storage_mode: StorageMode = Field(default="memory")
    # sheets モード時に必須。対象スプレッドシートの ID とワークシート名。
    spreadsheet_id: str = Field(default="")
    worksheet_name: str = Field(default="roster")
    # サービスアカウント鍵 JSON のパス。空なら ADC (Application Default Credentials)。
    google_credentials_path: str = Field(default="")

    # ── OCR ───────────────────────────────────────────────────────────
    ocr_provider: OcrProvider = Field(default="mock")

    # ── LIFF ──────────────────────────────────────────────────────────
    liff_id: str = Field(default="")
    # LIFF フォームがサブミットする API のベース URL（Cloud Run の公開 URL）。
    public_base_url: str = Field(default="")

    @property
    def line_configured(self) -> bool:
        """LINE_* が両方揃っているか。未設定なら webhook は 503。"""
        return bool(self.line_channel_secret and self.line_channel_access_token)

    @property
    def allowed_user_ids(self) -> frozenset[str]:
        """ホワイトリストを集合化。空要素は無視する。"""
        ids = (uid.strip() for uid in self.allowed_line_user_ids.split(","))
        return frozenset(uid for uid in ids if uid)

    def is_authorized(self, user_id: str) -> bool:
        """LINE user id が操作を許可されているか判定する。"""
        if self.allow_all_users:
            return True
        return bool(user_id) and user_id in self.allowed_user_ids


settings = Settings()

__all__ = ["OcrProvider", "Settings", "StorageMode", "settings"]
