// driving-license-bot — GCP production architecture spec.
// Source of truth: README "アーキテクチャの概要" + terraform/*.tf
// (cloud_run, admin_ui, cloudsql, firestore, batch, scheduler, workflows,
// secrets, backup_bucket, apis).
export const spec = {
  title: "driving-license-bot — GCP",
  subtitle: "LINE Bot · Cloud Run · Vertex AI (Claude/Gemini) · asia-northeast1",
  width: 1360,
  height: 760,
  groups: [
    { label: "VPC / project — asia-northeast1", x: 250, y: 150, w: 840, h: 470 },
  ],
  nodes: [
    { id: "line", label: "LINE Platform", sub: "Messaging API", icon: "x-line", x: 540, y: 24, cat: "external" },
    { id: "lb", label: "line-bot-service", sub: "Cloud Run · FastAPI (即時200)", icon: "gcp-cloud_run", x: 540, y: 132, cat: "compute" },
    { id: "tasks", label: "Cloud Tasks", sub: "enqueue ジョブ", icon: "x-cloudtasks", x: 540, y: 240, cat: "data" },
    { id: "agent", label: "agent-service", sub: "Cloud Run · Claude Agent SDK", icon: "gcp-cloud_run", x: 540, y: 348, cat: "compute" },

    { id: "vertex", label: "Vertex AI", sub: "Claude + Gemini cross-check", icon: "gcp-vertexai", x: 880, y: 348, cat: "ai" },

    { id: "firestore", label: "Firestore", sub: "セッション / ユーザー", icon: "gcp-firestore", x: 300, y: 300, cat: "data" },
    { id: "sql", label: "Cloud SQL", sub: "Postgres + pgvector 重複検査", icon: "gcp-cloud_sql", x: 300, y: 408, cat: "data" },
    { id: "bq", label: "BigQuery", sub: "出題履歴 (analytics 共用)", icon: "x-bigquery", x: 300, y: 516, cat: "data" },
    { id: "gcs", label: "Cloud Storage", sub: "標識画像 / 教則PDF / プール", icon: "gcp-cloud_storage", x: 540, y: 516, cat: "data" },

    { id: "batch", label: "Cloud Run Job", sub: "夜間 問題生成 batch", icon: "gcp-cloud_run", x: 820, y: 470, cat: "compute" },
    { id: "wf", label: "Workflows", sub: "generation pipeline", icon: "gcp-cloud_build", x: 820, y: 560, cat: "ops" },
    { id: "sched", label: "Cloud Scheduler", sub: "nightly トリガー", icon: "gcp-cloud_build", x: 1040, y: 470, cat: "ops" },

    { id: "admin", label: "admin-ui", sub: "Cloud Run · レビューUI", icon: "gcp-cloud_run", x: 880, y: 240, cat: "compute" },
    { id: "iap", label: "IAP", sub: "operator 認証", icon: "gcp-identity_and_access_management", x: 1120, y: 240, cat: "ops" },

    { id: "secret", label: "Secret Manager", sub: "LINE鍵 / DB / OAuth", icon: "gcp-secret_manager", x: 40, y: 300, w: 188, cat: "ops" },
    { id: "ar", label: "Artifact Registry", sub: "コンテナイメージ", icon: "gcp-artifact_registry", x: 40, y: 408, w: 188, cat: "ops" },
    { id: "obs", label: "Logging / Monitoring", sub: "ログ / アラート", icon: "gcp-cloud_logging", x: 40, y: 516, w: 188, cat: "ops" },
    { id: "backup", label: "Backup bucket", sub: "Firestore / SQL export", icon: "gcp-cloud_storage", x: 1120, y: 516, cat: "data" },
  ],
  edges: [
    { from: "line", to: "lb", label: "webhook" },
    { from: "lb", to: "tasks", label: "enqueue" },
    { from: "tasks", to: "agent", label: "dispatch" },
    { from: "agent", to: "vertex", label: "生成/採点" },
    { from: "agent", to: "firestore" },
    { from: "agent", to: "sql", label: "pgvector" },
    { from: "agent", to: "bq", dashed: true },
    { from: "agent", to: "gcs" },
    { from: "batch", to: "agent", dashed: true },
    { from: "wf", to: "batch" },
    { from: "sched", to: "wf", label: "nightly" },
    { from: "admin", to: "sql", dashed: true },
    { from: "iap", to: "admin", label: "auth" },
    { from: "lb", to: "secret", dashed: true },
    { from: "firestore", to: "backup", dashed: true },
  ],
};
