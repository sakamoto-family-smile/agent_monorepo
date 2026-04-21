"""アプリ全体の設定。

ENV=local / gcp で挙動を切替える単一の源。
アプリコードは `settings` を import して使う想定。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["local", "gcp"] = "local"

    service_name: str = "analytics-platform-demo"
    service_version: str = "0.1.0"

    analytics_data_dir: Path = Field(default=Path("./data"))
    analytics_compress: bool = False

    content_inline_threshold_bytes: int = 8192

    otel_exporter_otlp_endpoint: str = "http://localhost:6006/v1/traces"
    otel_exporter_otlp_headers: str = ""
    otel_sampling_ratio: float = 1.0

    log_level: str = "INFO"

    @property
    def raw_dir(self) -> Path:
        return self.analytics_data_dir / "raw"

    @property
    def uploaded_dir(self) -> Path:
        return self.analytics_data_dir / "uploaded"

    @property
    def dead_letter_dir(self) -> Path:
        return self.analytics_data_dir / "dead_letter"

    @property
    def payloads_dir(self) -> Path:
        return self.analytics_data_dir / "payloads"

    @property
    def duckdb_path(self) -> Path:
        return self.analytics_data_dir / "analytics.duckdb"

    def ensure_dirs(self) -> None:
        for d in (
            self.analytics_data_dir,
            self.raw_dir,
            self.uploaded_dir,
            self.dead_letter_dir,
            self.payloads_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
