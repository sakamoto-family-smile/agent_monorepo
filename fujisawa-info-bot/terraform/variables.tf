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
  default     = "fujisawa-info-bot"
  description = "Cloud Run Service 名 (Artifact Registry repo 名にも流用)。"
}

# ─────────────────────────────────────────────────────────────────────
# Cloud SQL (fujisawa-platform が作成済の `fujisawa_kb_db` を参照)
# ─────────────────────────────────────────────────────────────────────

variable "shared_cloudsql_instance_name" {
  type        = string
  description = "既存の Cloud SQL Postgres instance 名 (driving-license-bot の例: driving-license-bot-pg)。 fujisawa_kb_db DB はこの instance 上にある。"
}

variable "shared_cloudsql_instance_connection_name" {
  type        = string
  description = "既存 Cloud SQL instance の connection name (project:region:instance 形式)。 Cloud Run の Cloud SQL connector で利用。"
}

variable "kb_db_name" {
  type        = string
  default     = "fujisawa_kb_db"
  description = "fujisawa-platform が作成済の KB database 名。"
}

# ─────────────────────────────────────────────────────────────────────
# Cloud Run Service
# ─────────────────────────────────────────────────────────────────────

variable "image" {
  type        = string
  default     = ""
  description = "Cloud Run Service の Docker image URI (Artifact Registry)。 空文字列なら Cloud Run Service を作らない (chicken-and-egg: image を build してから埋める)。"
}

variable "min_instances" {
  type        = number
  default     = 0
  description = "Cloud Run Service の最小 instance 数。 0 でアイドル時のコスト 0。 災害時に push を捌くなら 1 に切替検討。"
}

variable "max_instances" {
  type        = number
  default     = 10
  description = "Cloud Run Service の最大 instance 数 (burst 制御)。"
}

variable "service_cpu" {
  type        = string
  default     = "1"
  description = "Cloud Run Service の CPU 数。"
}

variable "service_memory" {
  type        = string
  default     = "1Gi"
  description = "Cloud Run Service の memory。 FastAPI + LangGraph + Vertex Anthropic client 程度なら 1Gi で十分。"
}

variable "service_request_timeout_seconds" {
  type        = number
  default     = 60
  description = "Cloud Run Service の request timeout (秒)。 LINE webhook 3 秒ルールは internal、 ここは Cloud Run 側の上限。"
}

# ─────────────────────────────────────────────────────────────────────
# LLM
# ─────────────────────────────────────────────────────────────────────

variable "llm_provider" {
  type        = string
  default     = "vertex_gemini"
  description = "LLM provider。 mock | vertex_anthropic | vertex_gemini。 default は vertex_gemini (proposal §4.5 準拠 + 実 deploy で Anthropic Claude モデルが project に未有効化と判明したため、 Gemini に切替)。"
}

variable "vertex_region" {
  type        = string
  default     = "asia-northeast1"
  description = "Vertex AI で Anthropic Claude を呼ぶ region。 driving-license-bot 等の他エージェントと揃え asia-northeast1。 us-east5 は claude-sonnet-4-5@20250929 等が host されておらず 404 になる (2026-05-22 実 deploy で確認)。"
}

variable "anthropic_model" {
  type        = string
  default     = "claude-sonnet-4-5@20250929"
  description = "Vertex AI 経由の Anthropic Claude モデル名 (llm_provider=vertex_anthropic 時)。 default は driving-license-bot 同型。 Anthropic Claude は Vertex Model Garden で要 enable (未 enable 時は 404)。"
}

variable "gemini_model" {
  type        = string
  default     = "gemini-2.5-flash"
  description = "Vertex AI 経由の Gemini モデル名 (llm_provider=vertex_gemini 時)。 default は flash (proposal §4.5 sub-agent 用)。 高難度質問用に gemini-2.5-pro も asia-northeast1 で動作確認済。"
}

variable "rag_top_k" {
  type        = number
  default     = 5
  description = "RAG 検索の top-k。"
}
