// fujisawa-info-bot — GCP architecture spec.
// Source: README §1 (2サービス構成 api + agent-core, LangGraph Supervisor,
// Vertex Gemini + Claude fallback, Firestore + Cloud SQL via fujisawa-platform)
// + terraform/*.tf (cloud_run, cloudsql consumer, secrets, iam, artifact_registry).
export const spec = {
  title: "fujisawa-info-bot — GCP",
  subtitle: "藤沢市 生活情報 LINE Bot · LangGraph Supervisor · Vertex AI",
  width: 1320,
  height: 660,
  groups: [
    { label: "project — asia-northeast1", x: 250, y: 150, w: 800, h: 400 },
    { label: "fujisawa-platform (共有 KB)", x: 250, y: 470, w: 470, h: 130, stroke: "rgba(167,139,250,0.4)", fill: "rgba(167,139,250,0.06)" },
  ],
  nodes: [
    { id: "line", label: "LINE Platform", sub: "Messaging API", icon: "x-line", x: 540, y: 24, cat: "external" },
    { id: "api", label: "info-bot api", sub: "Cloud Run · FastAPI Webhook", icon: "gcp-cloud_run", x: 540, y: 132, cat: "compute" },
    { id: "agent", label: "agent-core", sub: "LangGraph Supervisor (intent/RAG)", icon: "gcp-cloud_run", x: 540, y: 260, cat: "compute" },

    { id: "vertex", label: "Vertex AI", sub: "Gemini 既定 + Claude fallback", icon: "gcp-vertexai", x: 870, y: 260, cat: "ai" },

    { id: "firestore", label: "Firestore", sub: "users / sessions / feedback", icon: "gcp-firestore", x: 300, y: 300, cat: "data" },
    { id: "sql", label: "Cloud SQL", sub: "fujisawa_kb_db (pgvector KB)", icon: "gcp-cloud_sql", x: 300, y: 500, cat: "data" },

    { id: "secret", label: "Secret Manager", sub: "LINE鍵 / KB DB パスワード", icon: "gcp-secret_manager", x: 40, y: 300, w: 188, cat: "ops" },
    { id: "ar", label: "Artifact Registry", sub: "コンテナイメージ", icon: "gcp-artifact_registry", x: 40, y: 400, w: 188, cat: "ops" },
    { id: "obs", label: "Cloud Logging", sub: "ログ / IAM 計装", icon: "gcp-cloud_logging", x: 1110, y: 300, cat: "ops" },
  ],
  edges: [
    { from: "line", to: "api", label: "webhook" },
    { from: "api", to: "agent", label: "graph 実行" },
    { from: "agent", to: "vertex", label: "intent / RAG" },
    { from: "agent", to: "firestore" },
    { from: "agent", to: "sql", label: "KB 検索" },
    { from: "api", to: "secret", dashed: true },
  ],
};
