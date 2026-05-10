"""ETL Job 共通の env 駆動設定 (proposal 0003 §4.5 / §4.8)。

Cloud Run Jobs から起動される ETL 群で参照する。Secret は Secret Manager 経由で
env として渡される (Phase 4-2h の terraform で配線)。
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EtlConfig(BaseSettings):
    """ETL Job 共通設定 (env: `FUJISAWA_ETL_*`)。"""

    model_config = SettingsConfigDict(
        env_prefix="FUJISAWA_ETL_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── DB 接続 ─────────────────────────────────────────────────────
    db_host: str = Field(description="Cloud SQL Auth Proxy 経由なら 127.0.0.1")
    db_port: int = Field(default=5432, gt=0, le=65535)
    db_user: str = Field(description="etl_role を持つ DB ユーザー")
    db_password: str = Field(description="DB パスワード (Secret Manager 経由)")
    db_name: str = Field(default="fujisawa_kb_db")
    db_pool_min: int = Field(default=1, ge=0)
    db_pool_max: int = Field(default=5, ge=1)

    # ── HTTP fetcher ────────────────────────────────────────────────
    user_agent: str = Field(
        description="連絡先 URL を含むこと (例: 'fujisawa-etl/0.1 (https://...)')"
    )
    min_interval_sec: float = Field(default=3.0, ge=0.0)

    # ── Embedding ───────────────────────────────────────────────────
    vertex_project_id: str | None = Field(
        default=None,
        description="None の場合は MockEmbeddingClient を使う (smoke / dry-run 用)",
    )
    vertex_location: str = Field(default="us-central1")
    embedding_model: str = Field(default="text-embedding-004")
    embedding_dim: int = Field(default=768, ge=1)

    # ── Job-specific URLs ───────────────────────────────────────────
    sitemap_url: str = Field(description="weekly_crawl_etl が起点とする sitemap.xml URL")

    # ── Job 個別 enable フラグ (Phase 0 で段階導入するため) ──────────
    weekly_crawl_enabled: bool = Field(default=True)
    monthly_vacancy_enabled: bool = Field(default=True)
    monthly_stats_compute_enabled: bool = Field(default=True)
    half_yearly_facility_enabled: bool = Field(default=True)
    yearly_navi_enabled: bool = Field(default=True)
    biyearly_admission_enabled: bool = Field(default=True)
    wayback_backfill_enabled: bool = Field(default=False)  # 一度きり、明示 ON

    @field_validator("user_agent")
    @classmethod
    def _user_agent_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("user_agent must be non-empty")
        return v

    @field_validator("db_password")
    @classmethod
    def _db_password_required(cls, v: str) -> str:
        if not v:
            raise ValueError("db_password must be non-empty")
        return v


__all__ = ["EtlConfig"]
