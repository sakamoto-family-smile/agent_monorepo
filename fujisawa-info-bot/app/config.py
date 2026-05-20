"""設定 (pydantic-settings) — env / .env から読み込み。

Phase 2: LLM / KB (knowledge_base) 関連の設定を追加した。 default は全て
mock / inmemory なので、 env 何も設定しなくても CI / 開発で graph が動く。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["mock", "vertex_anthropic"]
KBStoreMode = Literal["inmemory", "pgvector"]
EmbeddingProvider = Literal["mock", "vertex"]


class Settings(BaseSettings):
    """環境変数 / `.env` から読み込まれる設定一式。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FUJISAWA_INFO_BOT_",
        extra="ignore",
    )

    # ── LINE Messaging API ────────────────────────────────────────────
    # ChannelSecret は HMAC-SHA256 で X-Line-Signature を検証する鍵。
    # ChannelAccessToken は Reply / Push API 呼出時の Bearer。
    # どちらかが空文字列なら `line_configured = False` で webhook は 503 を返す。
    line_channel_secret: str = Field(default="", alias="LINE_CHANNEL_SECRET")
    line_channel_access_token: str = Field(default="", alias="LINE_CHANNEL_ACCESS_TOKEN")

    # ── LLM (Phase 2) ─────────────────────────────────────────────────
    # default は mock。 本番は env で vertex_anthropic に切替。
    llm_provider: LLMProvider = Field(default="mock", alias="LLM_PROVIDER")
    gcp_project_id: str = Field(default="", alias="GCP_PROJECT_ID")
    vertex_region: str = Field(default="us-east5", alias="VERTEX_REGION")
    # Vertex AI 経由の Anthropic Claude モデル名 (例: claude-haiku-4-5@20251001)
    anthropic_model: str = Field(
        default="claude-haiku-4-5@20251001",
        alias="ANTHROPIC_MODEL",
    )
    llm_max_tokens: int = Field(default=1024, alias="LLM_MAX_TOKENS")

    # ── Knowledge Base (Phase 2) ──────────────────────────────────────
    kb_store_mode: KBStoreMode = Field(default="inmemory", alias="KB_STORE_MODE")
    embedding_provider: EmbeddingProvider = Field(
        default="mock",
        alias="EMBEDDING_PROVIDER",
    )
    embedding_dim: int = Field(default=768, alias="EMBEDDING_DIM")
    # pgvector 接続情報 (kb_store_mode=pgvector 時に必須)
    cloud_sql_host: str = Field(default="", alias="CLOUD_SQL_HOST")
    cloud_sql_port: int = Field(default=5432, alias="CLOUD_SQL_PORT")
    cloud_sql_user: str = Field(default="", alias="CLOUD_SQL_USER")
    cloud_sql_password: str = Field(default="", alias="CLOUD_SQL_PASSWORD")
    cloud_sql_database: str = Field(default="fujisawa_kb_db", alias="CLOUD_SQL_DATABASE")

    # ── Feature flags ─────────────────────────────────────────────────
    feature_rag_enabled: bool = Field(default=True, alias="RAG_ENABLED")
    rag_top_k: int = Field(default=5, alias="RAG_TOP_K")

    @property
    def line_configured(self) -> bool:
        """LINE_* が両方揃っているかどうか。 未設定なら webhook handler は無効化扱い。"""
        return bool(self.line_channel_secret and self.line_channel_access_token)


settings = Settings()


__all__ = [
    "EmbeddingProvider",
    "KBStoreMode",
    "LLMProvider",
    "Settings",
    "settings",
]
