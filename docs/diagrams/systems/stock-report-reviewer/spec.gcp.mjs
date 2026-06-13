// stock-report-reviewer — GCP architecture spec.
// PROPOSAL-0013 (docs/PROPOSALS/0013-stock-report-review-pipeline.md) §3.5
// stock-analysis-agent の出力レポートを CrewAI ベースで品質レビューする
// パイプライン構成。
//
// トリガ方式: 案 B (Pub/Sub push subscription 直接) を採用。
// Cloud Tasks 層は持たず、Pub/Sub 自身の retry / DLQ topic で代替する。
// 二重通知レース (.md + .json の 2 ファイル書き) は subscription filter
// (`.json` 末尾のみ通す) で吸収。
// Vertex AI quota 保護のための rate limit は Cloud Run の max_instances=3
// で当面代用、本格的な per-queue rate limit が要れば Phase 2 で
// 案 A (Cloud Tasks 再導入) を別 PR で検討。
export const spec = {
  title: "stock-report-reviewer — GCP",
  subtitle: "CrewAI · Pub/Sub push · Vertex AI Gemini 2.5 · asia-northeast1",
  width: 1400,
  height: 760,
  groups: [
    { label: "VPC / project — asia-northeast1", x: 240, y: 120, w: 920, h: 520 },
  ],
  nodes: [
    // ── External actors ───────────────────────────────────────────────
    { id: "stock_agent", label: "stock-analysis-agent", sub: "Cloud Run (既存) · SQLite + GCS dual-write", icon: "gcp-cloud_run", x: 540, y: 24, cat: "compute" },
    { id: "human", label: "Human Reviewer", sub: "(approve / reject / revise)", icon: "gcp-users", x: 1180, y: 24, cat: "external" },

    // ── Ops (left side, outside VPC) ──────────────────────────────────
    { id: "secret", label: "Secret Manager", sub: "DB / API keys", icon: "gcp-secret_manager", x: 40, y: 200, w: 188, cat: "ops" },
    { id: "ar", label: "Artifact Registry", sub: "コンテナイメージ", icon: "gcp-artifact_registry", x: 40, y: 320, w: 188, cat: "ops" },
    { id: "obs", label: "Logging / Monitoring", sub: "alert / DLQ 通知", icon: "gcp-cloud_logging", x: 40, y: 440, w: 188, cat: "ops" },

    // ── Pipeline trigger (top row of VPC) ─────────────────────────────
    { id: "gcs_raw", label: "GCS raw/", sub: "<ticker>/<dt>.md + .json", icon: "gcp-cloud_storage", x: 310, y: 140, cat: "data" },
    { id: "pubsub", label: "Pub/Sub", sub: "topic: stock-report-created\nfilter: *.json", icon: "gcp-pubsub", x: 540, y: 140, cat: "data" },
    { id: "gcs_review", label: "GCS reviewed/", sub: "scores JSON · improved/", icon: "gcp-cloud_storage", x: 850, y: 140, cat: "data" },
    { id: "gcs_final", label: "GCS approved/", sub: "archived/ · dead/", icon: "gcp-cloud_storage", x: 1040, y: 140, cat: "data" },

    // ── Compute (middle row) ──────────────────────────────────────────
    { id: "worker", label: "review-worker", sub: "Cloud Run · CrewAI · push subscriber\nmax_instances=3", icon: "gcp-cloud_run", x: 540, y: 280, cat: "compute" },
    { id: "vertex", label: "Vertex AI", sub: "Gemini 2.5 Pro / Flash", icon: "gcp-vertexai", x: 850, y: 280, cat: "ai" },

    // ── Storage + UI (bottom row of VPC) ──────────────────────────────
    { id: "sql", label: "Cloud SQL", sub: "stock_review_db · 共有 instance", icon: "gcp-cloud_sql", x: 310, y: 420, cat: "data" },
    { id: "bq", label: "BigQuery", sub: "stock_review.reviews", icon: "x-bigquery", x: 540, y: 420, cat: "data" },
    { id: "ui", label: "review-ui", sub: "Cloud Run · approve / reject", icon: "gcp-cloud_run", x: 850, y: 420, cat: "compute" },
    { id: "iap", label: "IAP", sub: "operator 認証", icon: "gcp-identity_and_access_management", x: 1040, y: 420, cat: "ops" },
  ],
  edges: [
    // Ingestion: stock-analysis-agent から GCS への dual-write
    { from: "stock_agent", to: "gcs_raw", label: "dual-write (.md, .json)" },

    // Trigger pipeline: GCS event → Pub/Sub → review-worker (push 直接)
    // 案 B 採用: Cloud Tasks 層は持たず、Pub/Sub 自身の retry + DLQ topic を活用
    { from: "gcs_raw", to: "pubsub", label: "notify (.json filter)" },
    { from: "pubsub", to: "worker", label: "push subscription\nretry 5 + DLQ" },

    // CrewAI 実行: worker が Vertex Gemini を呼ぶ
    { from: "worker", to: "vertex", label: "CrewAI agents" },

    // worker からの出力
    { from: "worker", to: "gcs_review", label: "scores / improved" },
    { from: "worker", to: "sql", label: "review queue" },
    { from: "worker", to: "bq", label: "stream", dashed: true },

    // Human review flow
    { from: "human", to: "iap" },
    { from: "iap", to: "ui", label: "auth" },
    { from: "ui", to: "sql", label: "pending list", dashed: true },
    { from: "ui", to: "gcs_final", label: "approve/reject" },

    // Ops 接続
    { from: "secret", to: "worker", dashed: true },
    { from: "ar", to: "worker", dashed: true },
    { from: "worker", to: "obs", dashed: true },
    { from: "pubsub", to: "obs", label: "DLQ alert", dashed: true },
  ],
};
