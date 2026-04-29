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
    # Vertex AI 上の Anthropic モデル ID は `<base>@<YYYYMMDD>` 形式。
    # Anthropic 直接 API のモデル名（claude-opus-4-7 等）とは異なるため要注意。
    # 詳細: docs/VERTEX_ENABLEMENT.md §1.1
    vertex_claude_model: str = "claude-sonnet-4-5@20250929"
    vertex_gemini_model: str = "gemini-2.5-pro"

    # --- リポジトリバックエンド ---
    # `memory`: テスト・local 開発用 in-memory。Cloud Run 再起動でデータ消失。
    # `firestore`: 本番用、GOOGLE_CLOUD_PROJECT 必須。
    repository_backend: str = "memory"

    # --- Firestore ---
    firestore_database: str = "(default)"

    # --- Cloud Tasks (Phase 2+) ---
    cloud_tasks_queue: str = "driving-license-bot-jobs"
    cloud_tasks_location: str = "asia-northeast1"
    cloud_tasks_invoker_sa: str = ""

    # --- analytics-platform 連携 ---
    analytics_enabled: bool = True
    analytics_data_dir: str = "./data"
    analytics_storage_backend: str = "local"
    analytics_gcs_bucket: str = ""
    analytics_gcs_raw_prefix: str = "uploaded/"
    analytics_gcs_payload_prefix: str = "payloads/"
    analytics_compress: bool = False
    analytics_content_inline_threshold_bytes: int = 8192

    # --- OTel / Langfuse ---
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""
    otel_sampling_ratio: float = 1.0

    # --- security-platform / MCP Proxy ---
    security_mcp_proxy_url: str = "http://localhost:8080"
    security_mcp_proxy_mode: str = "passive"
    # 外部 HTTP egress を proxy 経由に強制する場合の URL（例: "http://localhost:8080"）。
    # 未設定なら直接外向き。Phase 2-F は declarative、Phase 4 で proxy 必須化検討。
    security_http_proxy_url: str = ""

    # --- 問題プール / 生成設定 ---
    question_pool_min_size: int = 30
    question_pool_target_size: int = 30
    generation_batch_size: int = 20
    seed_questions_path: str = "app/data/seed_questions.json"
    # Phase 2-X1: 出題プールのソース。"seed" でシード JSON、"bank" で
    # pgvector + Firestore の published 問題から動的構築。
    # 既定 "seed" は Phase 1 と同等動作 (後方互換)。bank プール ≥ 30 件が安定運用の目安。
    question_pool_source: str = "seed"
    # Phase 2-X1: bank プールの cache 自動更新間隔 (秒)。0 で無効。
    # FastAPI lifespan で N 秒ごとに refresh する。Cloud Run 単一インスタンスで
    # 1〜5 分程度が現実的。
    question_pool_refresh_interval_seconds: int = 180

    # --- agent / LLM 制御 ---
    # Question Generator が使う LLM プロバイダ。"claude" | "gemini"。
    # Claude は Vertex AI Marketplace 承認が必要。承認前 / 個人利用で承認しない場合は
    # "gemini" にして Gemini 単独で運用する（cross-check の多様性は減るが Phase 2 では
    # 全件人間レビュー必須なので品質担保は可能）。Quality Reviewer は常に Gemini。
    agent_llm_provider: str = "gemini"
    # true で MockLLMClient を返す。CI / 開発環境で誤って Vertex を叩かないため。
    agent_llm_mock: bool = False
    # 生成時のサンプリング温度（低めで決定的に）
    agent_temperature: float = 0.4
    agent_max_tokens: int = 4096

    # --- embedding 制御 ---
    # true で MockEmbeddingClient を返す。CI / 開発環境で誤って Vertex を叩かないため。
    embedding_mock: bool = False
    # Vertex AI text-embedding-004 のデフォルト次元
    embedding_model: str = "text-embedding-004"
    embedding_dim: int = 768

    # --- Question Bank（重複検査）---
    # `memory`: テスト・local 開発用。`pgvector`: 本番 Cloud SQL Postgres。
    question_bank_backend: str = "memory"
    # 類似度がこれを超えると「重複」と判断（cosine、0.0〜1.0）
    question_bank_dedup_threshold: float = 0.92
    # 類似度検索の上位件数
    question_bank_top_k: int = 5

    # --- Cloud SQL pgvector 接続 ---
    cloudsql_instance_connection_name: str = ""
    cloudsql_db: str = "question_bank"
    cloudsql_user: str = "app"
    cloudsql_password: str = ""
    cloudsql_host: str = ""  # Cloud SQL Auth Proxy 経由なら "127.0.0.1" 等
    cloudsql_port: int = 5432

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
