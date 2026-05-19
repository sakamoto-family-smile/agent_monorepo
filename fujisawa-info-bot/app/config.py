"""設定 (pydantic-settings) — env / .env から読み込み。

Phase 1 では LINE Channel の secret / access token のみ。 Phase 2+ で Vertex AI /
Firestore 等の設定が増えるたびに本ファイルに追加していく。
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """環境変数 / `.env` から読み込まれる設定一式。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FUJISAWA_INFO_BOT_",
        extra="ignore",
    )

    # LINE Messaging API
    # ChannelSecret は HMAC-SHA256 で X-Line-Signature を検証する鍵。
    # ChannelAccessToken は Reply / Push API 呼出時の Bearer。
    # どちらかが空文字列なら `line_configured = False` で webhook は 503 を返す。
    line_channel_secret: str = Field(default="", alias="LINE_CHANNEL_SECRET")
    line_channel_access_token: str = Field(default="", alias="LINE_CHANNEL_ACCESS_TOKEN")

    @property
    def line_configured(self) -> bool:
        """LINE_* が両方揃っているかどうか。 未設定なら webhook handler は無効化扱い。"""
        return bool(self.line_channel_secret and self.line_channel_access_token)


settings = Settings()


__all__ = ["Settings", "settings"]
