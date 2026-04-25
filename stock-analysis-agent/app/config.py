import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    app_env: str = os.getenv("APP_ENV", "local")
    log_level: str = os.getenv("LOG_LEVEL", "info")
    claude_code_oauth_token: str = os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "")

    # Database
    db_path: str = os.getenv("DB_PATH", "data/stock_analysis.db")

    # Data directories
    data_dir: str = os.getenv("DATA_DIR", "data")
    charts_dir: str = os.getenv("CHARTS_DIR", "data/charts")
    reports_dir: str = os.getenv("REPORTS_DIR", "data/reports")
    cache_dir: str = os.getenv("CACHE_DIR", "data/cache")
    dictionaries_dir: str = os.getenv("DICTIONARIES_DIR", "data/dictionaries")

    # Security Platform MCP Proxy URL (empty = direct MCP)
    mcp_proxy_url: str = os.getenv("MCP_PROXY_URL", "")

    # Cache settings
    price_cache_ttl_hours: int = int(os.getenv("PRICE_CACHE_TTL_HOURS", "24"))

    # Finnhub（未設定の場合はJSONユニバースのみを使用）
    finnhub_api_key: str = os.getenv("FINNHUB_API_KEY", "")

    # VertexAI settings
    vertex_ai_project: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    vertex_ai_location: str = os.getenv("VERTEX_AI_LOCATION", "us-east5")

    # ── 分析基盤 (analytics-platform) 連携 ──
    analytics_enabled: bool = os.getenv("ANALYTICS_ENABLED", "true").lower() == "true"
    analytics_data_dir: str = os.getenv("ANALYTICS_DATA_DIR", "./data/analytics")
    analytics_service_name: str = os.getenv(
        "ANALYTICS_SERVICE_NAME", "stock-analysis-agent"
    )
    analytics_compress: bool = os.getenv("ANALYTICS_COMPRESS", "false").lower() == "true"
    analytics_content_inline_threshold_bytes: int = int(
        os.getenv("ANALYTICS_CONTENT_INLINE_THRESHOLD_BYTES", "8192")
    )
    otel_exporter_otlp_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    otel_exporter_otlp_headers: str = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")
    otel_sampling_ratio: float = float(os.getenv("OTEL_SAMPLING_RATIO", "1.0"))
    service_version: str = os.getenv("SERVICE_VERSION", "0.1.0")

    # ── 分析基盤 GCP backend (Phase 5 Step 10) ──
    # `local` (既定) | `gcs`。`gcs` のとき content payload と JSONL の upload 先が
    # GCS に切り替わる。残りの GCS 設定は analytics_platform.gcp_config が env から読む:
    #   ANALYTICS_GCS_BUCKET / ANALYTICS_GCS_RAW_PREFIX / ANALYTICS_GCS_PAYLOAD_PREFIX
    #   ANALYTICS_GCP_PROJECT
    analytics_storage_backend: str = os.getenv(
        "ANALYTICS_STORAGE_BACKEND", "local"
    ).lower()
    # 周期的に LocalUploader.run_once() を回す間隔 (秒)。0 以下なら定期 upload 無効
    # (shutdown 時のみ 1 回 upload する)。`gcs` backend のときに意味を持つ。
    analytics_upload_interval_seconds: int = int(
        os.getenv("ANALYTICS_UPLOAD_INTERVAL_SECONDS", "300")
    )
    # LocalUploader の min_age_seconds。書込直後の file を upload しないためのヒステリシス。
    # default 30 秒。テストでは 0 にすると即時 upload できる。
    analytics_uploader_min_age_seconds: float = float(
        os.getenv("ANALYTICS_UPLOADER_MIN_AGE_SECONDS", "30")
    )

    # ── LINE Bot 連携 (Phase B: stateless) ──
    # LINE Developers Console > Messaging API > 「チャネル基本設定」「Messaging API」
    # から取得。両方未設定だと /api/line/webhook は 503 を返す。
    line_channel_secret: str = os.getenv("LINE_CHANNEL_SECRET", "")
    line_channel_access_token: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")

    @property
    def cors_origins(self):
        if self.app_env == "local":
            return ["http://localhost:3000", "http://127.0.0.1:3000"]
        return [os.getenv("FRONTEND_URL", "")]


settings = Settings()
