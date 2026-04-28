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
