variable "project_id" {
  type        = string
  description = "GCP project ID (例: sakamomo-family-agent)。"
}

variable "region" {
  type        = string
  default     = "asia-northeast1"
  description = "リソースを作成する region。"
}

variable "service_name" {
  type        = string
  default     = "stock-analysis-line"
  description = "Cloud Run Service 名 (Artifact Registry repo 名にも流用)。"
}

# ─────────────────────────────────────────────────────────────────────
# Cloud SQL (PROPOSAL-0011 P2-B: shared-pg に相乗り)
# ─────────────────────────────────────────────────────────────────────

variable "shared_cloudsql_instance_name" {
  type        = string
  default     = "shared-pg"
  description = "共有 Cloud SQL Postgres インスタンス名 (PROPOSAL-0009 P1)。"
}

variable "shared_cloudsql_instance_connection_name" {
  type        = string
  default     = "sakamomo-family-agent:asia-northeast1:shared-pg"
  description = "共有インスタンスの connection name (project:region:instance)。Cloud Run の Cloud SQL connector が使う。"
}

variable "db_name" {
  type        = string
  default     = "stock_analysis_db"
  description = "stock 専用 database 名 (shared-pg 上に作成)。"
}

variable "db_user" {
  type        = string
  default     = "stock_analysis_user"
  description = "stock 専用 DB user 名。password は terraform 生成 → Secret Manager 投入。"
}

# ─────────────────────────────────────────────────────────────────────
# Cloud Run Service
# ─────────────────────────────────────────────────────────────────────

variable "image" {
  type        = string
  default     = ""
  description = "Cloud Run Service の Docker image URI (Artifact Registry)。空文字列なら Cloud Run Service を作らない (chicken-and-egg: image を build してから埋める)。"
}

variable "min_instances" {
  type        = number
  default     = 0
  description = "webhook の最小 instance 数。P3-A で分析を Cloud Tasks/worker に委譲したため 0 で可 (enqueue のみで軽量)。初回リクエストは cold start。"
}

variable "max_instances" {
  type        = number
  default     = 3
  description = "最大 instance 数 (burst 制御 + コスト上限)。個人利用なので小さめ。"
}

variable "service_cpu" {
  type        = string
  default     = "1"
  description = "CPU 数。Claude CLI (node) + brave MCP (node) + python の同時実行。重ければ 2 に。"
}

variable "service_memory" {
  type        = string
  default     = "2Gi"
  description = "memory。claude-agent-sdk subprocess + matplotlib + pandas で 2Gi 目安。"
}

variable "service_request_timeout_seconds" {
  type        = number
  default     = 300
  description = "Cloud Run request timeout (秒)。webhook 自体は即 200 だが余裕を持たせる。"
}

# ─────────────────────────────────────────────────────────────────────
# アプリ設定 (PROPOSAL-0011 P1)
# ─────────────────────────────────────────────────────────────────────

variable "public_base_url" {
  type        = string
  default     = ""
  description = "チャート画像 / 全文 Markdown を配信する公開 URL のベース (末尾スラッシュ無し)。初回 deploy 後に Cloud Run URL を埋めて 2 回目 apply で反映する。空なら Flex 要約のみ配信。"
}

variable "family_user_ids" {
  type        = string
  default     = ""
  description = "許可する LINE userId の CSV。空なら全許可 (dev)。本番は家族の userId を必ず設定 (Opus 濫用防止)。"
}

variable "analyze_rate_limit_per_day" {
  type        = number
  default     = 20
  description = "1 ユーザ 1 日あたりの `分析` 回数上限 (Opus コスト抑制)。0 以下で無制限。"
}

variable "log_level" {
  type        = string
  default     = "info"
  description = "ログレベル (debug/info/warning/error)。"
}

variable "edinet_enabled" {
  type        = bool
  default     = false
  description = "EDINET 法定開示連携。P1 は false (yfinance + Brave のみ)。P3 で true + EDINET_API_KEY 投入。"
}

# ─────────────────────────────────────────────────────────────────────
# Cloud Tasks worker (PROPOSAL-0011 P3-A)
# ─────────────────────────────────────────────────────────────────────

variable "worker_service_name" {
  type        = string
  default     = "stock-analysis-worker"
  description = "分析 worker の Cloud Run Service 名 (webhook と同一イメージ)。"
}

variable "worker_min_instances" {
  type        = number
  default     = 0
  description = "worker 最小 instance 数。タスク到着時にスケール、アイドルで 0。"
}

variable "worker_max_instances" {
  type        = number
  default     = 3
  description = "worker 最大 instance 数 (並列度の上限。queue の concurrency と揃える)。"
}

variable "worker_cpu" {
  type        = string
  default     = "1"
  description = "worker の CPU 数。"
}

variable "worker_memory" {
  type        = string
  default     = "2Gi"
  description = "worker の memory (claude-agent-sdk subprocess + matplotlib)。"
}

variable "worker_request_timeout_seconds" {
  type        = number
  default     = 900
  description = "worker の request timeout (秒)。EDINET 有効化で 1〜5 分かかるため長め。"
}

variable "tasks_queue_name" {
  type        = string
  default     = "stock-analysis"
  description = "Cloud Tasks queue 名。"
}

variable "tasks_max_concurrent_dispatches" {
  type        = number
  default     = 3
  description = "queue の同時 dispatch 上限 (= 同時分析数)。worker_max_instances と揃える。"
}

variable "tasks_max_dispatches_per_second" {
  type        = number
  default     = 1
  description = "queue の毎秒 dispatch 上限。"
}

variable "tasks_max_attempts" {
  type        = number
  default     = 3
  description = "タスクの最大試行回数 (worker のリトライ判定にも env で渡す)。"
}

variable "media_retention_days" {
  type        = number
  default     = 1
  description = "media バケットのオブジェクト保持日数 (一時配信のみ)。"
}

# ─────────────────────────────────────────────────────────────────────
# analytics-platform 連携 (PROPOSAL-0011 P2-A / PROPOSAL-0010 P5)
# ─────────────────────────────────────────────────────────────────────

variable "analytics_storage_backend" {
  type        = string
  default     = "pubsub"
  description = "イベント送信 backend。local | gcs | pubsub。P2-A で pubsub に切替 (Pub/Sub→GCS→BQ で本番イベントを永続化)。"
}

variable "analytics_pubsub_topic" {
  type        = string
  default     = "analytics-events"
  description = "analytics-platform の events topic 短縮名 (analytics-platform terraform の name_prefix=analytics → analytics-events)。backend=pubsub のとき必須。"
}

# 前提: この SA (sa-stock-analysis-line) を analytics-platform terraform の
# `publisher_service_account_emails` に追記して apply 済であること
# (events topic への roles/pubsub.publisher 付与は analytics 側で行う)。
