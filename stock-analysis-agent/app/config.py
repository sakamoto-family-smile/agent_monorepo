import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    app_env: str = os.getenv("APP_ENV", "local")
    log_level: str = os.getenv("LOG_LEVEL", "info")
    claude_code_oauth_token: str = os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "")

    # Database (PROPOSAL-0011 P2-B: SQLAlchemy async)
    # 優先度: DATABASE_URL > DB_HOST/DB_USER/DB_NAME(+DB_PASSWORD)組立 > db_path(sqlite)
    #   - dev/test: sqlite+aiosqlite:///{db_path}
    #   - prod:     postgresql+asyncpg://user:pass@/db?host=/cloudsql/<conn>
    db_path: str = os.getenv("DB_PATH", "data/stock_analysis.db")
    database_url: str = os.getenv("DATABASE_URL", "")
    # Cloud SQL connector (unix socket) 用の分割指定。DATABASE_URL 未設定時に組み立てる。
    db_host: str = os.getenv("DB_HOST", "")  # 例: /cloudsql/proj:region:shared-pg
    db_user: str = os.getenv("DB_USER", "")
    db_name: str = os.getenv("DB_NAME", "")
    db_password: str = os.getenv("DB_PASSWORD", "")
    # スキーマ作成方法: true(既定/dev) は init_db で create_all + seed。
    # prod Postgres は alembic で管理するため false にし、init_db は seed のみ行う。
    db_auto_create: bool = os.getenv("DB_AUTO_CREATE", "true").lower() == "true"

    @property
    def resolved_database_url(self) -> str:
        """最終的な SQLAlchemy 非同期 URL を解決する。"""
        if self.database_url:
            return self.database_url
        if self.db_host and self.db_user and self.db_name:
            from urllib.parse import quote

            pw = quote(self.db_password, safe="")
            return (
                f"postgresql+asyncpg://{self.db_user}:{pw}"
                f"@/{self.db_name}?host={self.db_host}"
            )
        return f"sqlite+aiosqlite:///{self.db_path}"

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

    # ── 分析基盤 GCP backend (Phase 5 Step 10 / PROPOSAL-0010 P5-3) ──
    # `local` (既定) | `gcs` | `pubsub`。
    #   - local : ローカル JSONL のみ (dev)
    #   - gcs   : ローカル JSONL を LocalUploader で GCS へ転送 (案B 互換)
    #   - pubsub: イベント行を直接 Pub/Sub topic に publish (PROPOSAL-0010 入口)
    # 残りの GCS 設定は analytics_platform.gcp_config が env から読む:
    #   ANALYTICS_GCS_BUCKET / ANALYTICS_GCS_RAW_PREFIX / ANALYTICS_GCS_PAYLOAD_PREFIX
    analytics_storage_backend: str = os.getenv(
        "ANALYTICS_STORAGE_BACKEND", "local"
    ).lower()
    # backend=pubsub のとき必須。topic 短縮名 (例 "analytics-events") かフルパス
    # (projects/<p>/topics/<name>)。未設定なら local JSONL に fallback。
    analytics_pubsub_topic: str = os.getenv("ANALYTICS_PUBSUB_TOPIC", "")
    # Pub/Sub / GCS の project_id。短縮名 topic のとき必須 (未指定なら ADC 推論)。
    analytics_gcp_project: str = os.getenv("ANALYTICS_GCP_PROJECT", "")
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

    # ── PROPOSAL-0011 P1: チャート画像 / 全文レポート配信 ──
    # LINE の ImageMessage / 全文 DL リンクは HTTPS 公開 URL を要求する。
    # Cloud Run なら `https://<service>-<...>.run.app`、ローカルは ngrok の URL。
    # 末尾スラッシュ不要、空なら画像/全文 URL の生成を skip し Flex 要約のみ送る。
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

    # 一時 store の容量・TTL (プロセス内 LRU + TTL。再起動で消える MVP 仕様)
    image_store_max_entries: int = int(os.getenv("IMAGE_STORE_MAX_ENTRIES", "50"))
    image_store_ttl_seconds: int = int(os.getenv("IMAGE_STORE_TTL_SECONDS", "3600"))
    report_store_max_entries: int = int(os.getenv("REPORT_STORE_MAX_ENTRIES", "50"))
    report_store_ttl_seconds: int = int(os.getenv("REPORT_STORE_TTL_SECONDS", "3600"))

    # ── PROPOSAL-0011 P3-A: media (チャート/全文) 配信 backend ──
    # memory (既定): インメモリ store + public_base_url で配信 (単一 instance 用)。
    # gcs: GCS にアップロードして公開 URL を返す (worker 複数 instance 対応)。
    media_backend: str = os.getenv("MEDIA_BACKEND", "memory").lower()
    media_gcs_bucket: str = os.getenv("MEDIA_GCS_BUCKET", "")
    media_gcs_public_base: str = os.getenv(
        "MEDIA_GCS_PUBLIC_BASE", "https://storage.googleapis.com"
    ).rstrip("/")

    # ── PROPOSAL-0011 P3-A: Cloud Tasks 分散非同期 ──
    # true のとき webhook は分析を Cloud Tasks に enqueue し、worker run が実行する。
    # false (dev/test) のときは従来通り in-process BackgroundTasks で実行。
    tasks_enabled: bool = os.getenv("TASKS_ENABLED", "false").lower() == "true"
    # queue のフルパス: projects/<p>/locations/<loc>/queues/<name>
    tasks_queue: str = os.getenv("TASKS_QUEUE", "")
    # worker の分析エンドポイント URL (例: https://stock-analysis-worker-...run.app/api/tasks/analyze)
    tasks_worker_url: str = os.getenv("TASKS_WORKER_URL", "")
    # Cloud Tasks が OIDC token を発行する invoker SA email (worker が検証)
    tasks_invoker_sa: str = os.getenv("TASKS_INVOKER_SA", "")
    # Cloud Tasks の最大試行回数 (worker のリトライ判定に使う)
    tasks_max_attempts: int = int(os.getenv("TASKS_MAX_ATTEMPTS", "3"))

    # ── PROPOSAL-0011 P1: アクセス制御 / コスト上限 ──
    # 許可ユーザ (LINE userId) の CSV。空なら全許可 (dev)。webhook は public のため、
    # Claude Opus を濫用されないよう本番では家族の userId を必ず設定する。
    family_user_ids: str = os.getenv("FAMILY_USER_IDS", "")
    # 1 ユーザあたりの `分析` 1 日上限 (Opus コスト抑制)。0 以下で無制限。
    analyze_rate_limit_per_day: int = int(os.getenv("ANALYZE_RATE_LIMIT_PER_DAY", "20"))

    # PROPOSAL-0012: 1 ユーザーのマイリスト登録上限 (yfinance バッチ負荷抑制)
    watchlist_max_items: int = int(os.getenv("WATCHLIST_MAX_ITEMS", "30"))

    @property
    def family_user_id_set(self) -> frozenset[str]:
        if not self.family_user_ids:
            return frozenset()
        return frozenset(
            uid.strip() for uid in self.family_user_ids.split(",") if uid.strip()
        )

    # ── EDINET 統合 (proposal 0006 Phase 1d) ──
    # EDINET API v2 で有報・四半期報告書を取得し、 Claude 分析に投入する。
    # false (既定) のとき EDINET 経路は完全に skip され、 既存の yfinance + Brave Search
    # で完結する。
    edinet_enabled: bool = os.getenv("EDINET_ENABLED", "false").lower() == "true"
    # API key は disclosure2.edinet-fsa.go.jp で無料登録
    edinet_api_key: str = os.getenv("EDINET_API_KEY", "")
    # ticker → EDINET code 解決用 CSV (公式 Edinetcode.csv)。 未設定だと resolver
    # 無しで起動するが、 collector は早期に skip する。
    edinet_code_csv_path: str = os.getenv("EDINET_CODE_CSV_PATH", "")
    # cache backend: "local" | "gcs"
    edinet_cache_backend: str = os.getenv("EDINET_CACHE_BACKEND", "local").lower()
    edinet_cache_root: str = os.getenv("EDINET_CACHE_ROOT", "./data/edinet")
    edinet_cache_gcs_bucket: str = os.getenv("EDINET_CACHE_GCS_BUCKET", "")
    edinet_cache_gcs_prefix: str = os.getenv("EDINET_CACHE_GCS_PREFIX", "edinet/")
    # 1 銘柄あたり取得する直近四半期報告書の本数
    edinet_quarterly_lookback: int = int(os.getenv("EDINET_QUARTERLY_LOOKBACK", "4"))
    # EDINET API 連続 request の最小間隔 (秒)
    edinet_min_interval_sec: float = float(os.getenv("EDINET_MIN_INTERVAL_SEC", "1.0"))
    # 最新書類検索の窓 (日)。 Phase 1d の orchestrator 直接 fetch 経路で使う。
    # Phase 1e の DB lookup ベースでは形式的 (実質ほぼ即時 lookup)
    edinet_search_window_days: int = int(os.getenv("EDINET_SEARCH_WINDOW_DAYS", "400"))
    # daily batch の rolling 窓日数。 status 系の遅延変更 (取下げ / 開示停止)
    # を捕捉するため 7 日が default (proposal §4.1)
    edinet_daily_window_days: int = int(os.getenv("EDINET_DAILY_WINDOW_DAYS", "7"))

    # XBRL parser を使って Tier 1+2 構造化数値を抽出するか (Phase 2b)。
    # true のとき edinet_collector が PDF に加えて XBRL zip も DL し parse 結果を
    # `EdinetFilingResult.financials` に格納する。 軽量 deploy で `[xbrl]` extras を
    # 入れない場合は false にする (parse は警告ログだけ出して skip)。
    edinet_enable_xbrl: bool = os.getenv("EDINET_ENABLE_XBRL", "true").lower() == "true"

    @property
    def cors_origins(self):
        if self.app_env == "local":
            return ["http://localhost:3000", "http://127.0.0.1:3000"]
        return [os.getenv("FRONTEND_URL", "")]


settings = Settings()
