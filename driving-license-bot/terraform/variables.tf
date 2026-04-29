variable "project_id" {
  type        = string
  description = "GCP project id (e.g. sakamoto-family-agent)."
}

variable "region" {
  type        = string
  description = "Default region for regional resources."
  default     = "asia-northeast1"
}

variable "name_prefix" {
  type        = string
  description = "Resource name prefix to scope all driving-license-bot resources."
  default     = "driving-license-bot"
}

# ---- Cloud Run line-bot-service ----

variable "line_bot_min_instances" {
  type        = number
  description = "Cloud Run min instances for line-bot-service. 1 で常時起動（コールドスタート回避）。0 でコスト削減（dev only）。"
  default     = 1
}

variable "line_bot_max_instances" {
  type        = number
  description = "Cloud Run max instances for line-bot-service."
  default     = 3
}

variable "line_bot_cpu" {
  type        = string
  description = "Cloud Run CPU allocation (e.g. \"1\")."
  default     = "1"
}

variable "line_bot_memory" {
  type        = string
  description = "Cloud Run memory (e.g. \"512Mi\")."
  default     = "512Mi"
}

variable "line_bot_image" {
  type        = string
  description = "Full Artifact Registry image URI to deploy. apply 前に Cloud Build で push する想定（README 参照）。空文字列なら Cloud Run service の deploy をスキップする。"
  default     = ""
}

variable "line_bot_invoker_members" {
  type        = list(string)
  description = "line-bot Cloud Run の invoker。LINE Webhook はパブリックなので allUsers が既定。"
  default     = ["allUsers"]
}

# ---- Firestore ----

variable "firestore_location" {
  type        = string
  description = "Firestore database location (asia-northeast1 等)。一度作ると変更不可。"
  default     = "asia-northeast1"
}

# ---- Artifact Registry ----

variable "ar_repo_name" {
  type        = string
  description = "Artifact Registry Docker repo name."
  default     = "driving-license-bot"
}

# ---- 安全装置 ----

variable "force_destroy" {
  type        = bool
  description = "true で `terraform destroy` 時にバケット内オブジェクトも一緒に削除する。dev/PoC 限定。本番は false。"
  default     = true
}

variable "deletion_protection" {
  type        = bool
  description = "Firestore database 等の deletion_protection。dev/PoC では false で teardown を容易に。"
  default     = false
}

# ---- Cloud SQL Postgres + pgvector (Phase 2-A) ----

variable "cloudsql_tier" {
  type        = string
  description = "Cloud SQL machine tier。PoC 既定の db-f1-micro は ~\\$10/月。本番は db-custom-1-3840 等に上げる。"
  default     = "db-f1-micro"
}

variable "cloudsql_disk_size_gb" {
  type        = number
  description = "Cloud SQL ディスクサイズ (GB)。SSD 既定。disk_autoresize=false なので明示上限。"
  default     = 10
}

variable "cloudsql_deletion_protection" {
  type        = bool
  description = "Cloud SQL instance の deletion_protection。dev/PoC では false で teardown を容易に。"
  default     = false
}

variable "cloudsql_backup_enabled" {
  type        = bool
  description = "Cloud SQL automated backup を有効化。PoC でも有効推奨（コスト微増）。"
  default     = true
}

variable "cloudsql_authorized_networks" {
  type = list(object({
    name  = string
    value = string
  }))
  description = "Cloud SQL の authorized networks。基本的に空（Cloud SQL Auth Proxy 経由を想定）。一時的なローカル直接接続用に CIDR 追加可。"
  default     = []
}

# ---- Cloud Run Job (Phase 2-B 自動生成バッチ) ----

variable "batch_image" {
  type        = string
  description = "Cloud Run Job (driving-license-bot-batch) で使う image URI。空文字列なら Job / Workflow / Scheduler を deploy しない (chicken-and-egg 回避)。line-bot と同 image を使う想定。"
  default     = ""
}

variable "batch_cpu" {
  type        = string
  description = "Cloud Run Job CPU 割当。"
  default     = "1"
}

variable "batch_memory" {
  type        = string
  description = "Cloud Run Job memory 割当。embedding 計算等で 1Gi が無難。"
  default     = "1Gi"
}

variable "batch_task_timeout_seconds" {
  type        = number
  description = "Cloud Run Job 1 タスクの最大実行時間 (秒)。30 分既定。"
  default     = 1800
}

variable "batch_max_retries" {
  type        = number
  description = "Cloud Run Job 失敗時の自動 retry 回数。"
  default     = 2
}

variable "generation_batch_size" {
  type        = number
  description = "1 バッチで生成する問題数。Cloud Run Job の --total に渡る。"
  default     = 20
}

variable "batch_schedule_cron" {
  type        = string
  description = "Cloud Scheduler の cron 式 (Asia/Tokyo)。既定: 02:00 JST 毎日。"
  default     = "0 2 * * *"
}

variable "agent_llm_provider" {
  type        = string
  description = "Question Generator が使う LLM プロバイダ。'gemini' (既定、Marketplace 不要) または 'claude' (Vertex AI Marketplace 承認後)。"
  default     = "gemini"

  validation {
    condition     = contains(["gemini", "claude"], var.agent_llm_provider)
    error_message = "agent_llm_provider must be 'gemini' or 'claude'."
  }
}

# ---- review-admin-ui (Phase 2-C3) ----

variable "review_admin_image" {
  type        = string
  description = "review-admin-ui の Cloud Run image URI。line-bot と同 image を共有 (CMD で uvicorn review_admin_ui.main:app に切替)。空なら admin-ui を deploy しない。"
  default     = ""
}

variable "review_admin_min_instances" {
  type        = number
  description = "review-admin-ui の min instances。運営者 1 人なら 0 で十分（cold start ~3s）。"
  default     = 0
}

variable "review_admin_max_instances" {
  type        = number
  description = "review-admin-ui の max instances。"
  default     = 2
}

variable "review_admin_cpu" {
  type        = string
  description = "review-admin-ui の CPU 割当。"
  default     = "1"
}

variable "review_admin_memory" {
  type        = string
  description = "review-admin-ui の memory 割当。"
  default     = "512Mi"
}

variable "review_admin_allowed_emails" {
  type        = list(string)
  description = "review-admin-ui への IAP アクセスを許可する Google アカウント email のリスト。空なら誰もアクセスできない（fail-closed）。"
  default     = []
}

# ---- Workload Identity Federation (CI 用) ----

variable "enable_wif" {
  type        = bool
  description = "true で GitHub Actions 用 Workload Identity Federation を作成。Pool / Provider / SA / IAM binding。後段の `terraform plan` を CI 化するために使う。"
  default     = false
}

variable "github_repo" {
  type        = string
  description = "WIF が信頼する GitHub リポジトリ (owner/repo 形式)。enable_wif=true の時のみ使われる。"
  default     = "sakamoto-family-smile/agent_monorepo"
}

variable "tfstate_bucket" {
  type        = string
  description = "tfstate を保存している GCS バケット名 (scripts/bootstrap_gcp.sh で作成済)。WIF SA に objectViewer を付与するためだけに使う。"
  default     = ""
}
