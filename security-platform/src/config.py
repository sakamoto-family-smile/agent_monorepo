"""Application configuration loaded from .env and environment variables."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / "config" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR}/data/security.db"

    # API Keys
    nvd_api_key: str = ""  # Required for full NVD rate limits (50 req/30s vs 5 req/30s)
    github_token: str = ""
    anthropic_api_key: str = ""
    vertex_ai_project: str = ""   # GCP project ID for Vertex AI
    vertex_ai_location: str = "us-central1"  # Vertex AI region
    llm_provider: str = ""  # "claude" | "gemini" | "" (auto-detect)

    # Notifications
    slack_webhook_url: str = ""

    # LINE Messaging API (Bot channel) — used by src/notifier/line.py
    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    line_user_ids: str = ""  # CSV of LINE userId (recipients of push notifications)

    # LINE Notify (DEPRECATED — サービスは 2025/03/31 に終了)。
    # 後方互換のため設定自体は残し、notifier 側で deprecation 警告を出す。
    line_notify_token: str = ""

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notification_email: str = ""

    # Server settings — コンテナ / dev サーバで全 interface にバインドするのが
    # 既定値 (本番は env で上書き or リバースプロキシ前提)。bandit B104 は
    # 意図的なので nosec で明示的に抑止する。
    dashboard_host: str = "0.0.0.0"  # nosec B104
    dashboard_port: int = 8000
    proxy_host: str = "0.0.0.0"  # nosec B104
    proxy_port: int = 8080

    # ── 脆弱性対応 (A1 intel / A2 detection / B remediation) ──────────────
    # 生データ・運用 DB (SQLite)・分析 DB (DuckDB)・イベントログの置き場所。
    data_dir: Path = BASE_DIR / "data"

    # A1: 情報源
    osv_base_url: str = "https://osv-vulnerabilities.storage.googleapis.com"
    osv_ecosystems: str = ""  # CSV。空なら ecosystems.txt の全エコシステム
    osv_full_refresh_days: int = 7  # 全量ダンプの再取得間隔
    osv_incremental_max_records: int = 3000  # 超えたら該当エコシステムを全量取得に切替
    osv_raw_full_snapshots_kept: int = 2  # data/raw/osv の全量スナップショット保持数
    raw_retention_days: int = 30  # KEV・EPSS・OSV 差分の生データ保持日数 (全量は世代数で管理)
    min_free_disk_gb: float = 10.0  # data/ の空きがこれを下回ったら大きな取得を止める (0 で無効)
    healthcheck_ping_base: str = ""  # 例: https://hc-ping.com/<ping-key>。空なら ping しない
    kev_url: str = (
        "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
    )
    epss_url: str = "https://epss.empiricalsecurity.com/epss_scores-current.csv.gz"
    epss_event_delta: float = 0.1  # この幅以上の上昇で advisory.changed を出す
    http_timeout_seconds: float = 60.0

    # A2: 照合の入力。コンテナではモノレポを読み取り専用で /repo にマウントする
    repo_dir: Path = BASE_DIR.parent
    services_path: Path = BASE_DIR / "config" / "services.yaml"
    detection_scan_interval_minutes: int = 60

    # 分析 DB (DuckDB) の再構築間隔
    analytics_interval_minutes: int = 60


settings = Settings()
