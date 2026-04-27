"""アプリ設定 (pydantic-settings)。

環境変数 (または .env) から読み込む。テストは monkeypatch.setenv + importlib.reload で
`settings` を再構築する運用 (piyolog-analytics / lifeplanner-agent と同パターン)。
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # --- App identity ---
    service_name: str = "driving-license-bot-line"
    service_version: str = "0.1.0"
    env: str = "local"
    log_level: str = "INFO"

    # --- LINE ---
    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    # Messaging API のチャネル ID（数値）。複数 Bot 名寄せの逆引きキーとして使う。
    # `internal_uid` と紐付くため secret 値からの導出はせず明示設定する。
    line_channel_id: str = ""
    operator_line_user_ids: str = ""

    # --- LINE Login (Phase 2+ で利用、Phase 1 では未使用) ---
    line_login_channel_id: str = ""
    line_login_channel_secret: str = ""

    # --- GCP / Vertex AI (Phase 2+ で実利用、Phase 1 では未使用) ---
    google_cloud_project: str = ""
    anthropic_vertex_project_id: str = ""
    cloud_ml_region: str = "asia-northeast1"
    vertex_claude_model: str = "claude-opus-4-7"
    vertex_gemini_model: str = "gemini-2.5-pro"

    # --- Firestore (Phase 2+ で実利用、Phase 1 は in-memory) ---
    firestore_database: str = "(default)"

    # --- Cloud Tasks (Phase 2+) ---
    cloud_tasks_queue: str = "driving-license-bot-jobs"
    cloud_tasks_location: str = "asia-northeast1"
    cloud_tasks_invoker_sa: str = ""

    # --- analytics-platform 連携 ---
    analytics_data_dir: str = "./data"
    analytics_storage_backend: str = "local"
    analytics_gcs_bucket: str = ""
    analytics_gcs_raw_prefix: str = "uploaded/"
    analytics_gcs_payload_prefix: str = "payloads/"

    # --- OTel / Langfuse ---
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""
    otel_sampling_ratio: float = 1.0

    # --- security-platform / MCP Proxy ---
    security_mcp_proxy_url: str = "http://localhost:8080"
    security_mcp_proxy_mode: str = "passive"

    # --- 問題プール / 生成設定 ---
    question_pool_min_size: int = 30
    question_pool_target_size: int = 30
    generation_batch_size: int = 20
    seed_questions_path: str = "app/data/seed_questions.json"

    # --- レビュー Web UI ---
    review_admin_allowed_emails: str = ""

    @property
    def operator_user_id_set(self) -> frozenset[str]:
        if not self.operator_line_user_ids:
            return frozenset()
        return frozenset(
            uid.strip() for uid in self.operator_line_user_ids.split(",") if uid.strip()
        )

    @property
    def line_configured(self) -> bool:
        return bool(self.line_channel_secret and self.line_channel_access_token)


settings = Settings()
