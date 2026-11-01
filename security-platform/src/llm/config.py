"""extractor の設定。config/llm.env から extractor コンテナにだけ渡す (config/.env は読まない)。"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LlmSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_", extra="ignore")

    provider: str = "claude-code"  # claude-code / fake (anthropic / gemini は L4 PR4)
    model: str = "haiku"
    daily_limit: int = 50  # 1 日に LLM を呼ぶ回数の上限
    run_hour: int = 3  # 常駐で動く時刻 (timezone の時)。Max プランの上限は対話と共有なので夜に回す
    window_hours: int = 3
    timezone: str = "Asia/Tokyo"
    claude_binary: str = "claude"
    claude_code_oauth_token: str = Field(default="", validation_alias="CLAUDE_CODE_OAUTH_TOKEN")
