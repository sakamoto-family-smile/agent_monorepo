// Monorepo GCP overview — system-of-systems architecture.
// Shows GCP-deployed agent services, the shared platforms they integrate with,
// and the common GCP data/AI plane underneath.
//
// Integration map (verified from pyproject path deps / config / compose):
//   analytics-platform 計装元: driving-license, piyolog, stock, lifeplanner,
//                              tech-news, hotcook
//   security-platform MCP proxy 利用: driving-license, kanie-lab, stock
//   fujisawa-platform KB 参照: fujisawa-info-bot
//   llm-client 利用: driving-license, fujisawa-info, lifeplanner, tech-news
export const spec = {
  title: "agent_monorepo — GCP 全体構成",
  subtitle: "エージェントサービス × 共有プラットフォーム × 共通 GCP データ/AI プレーン",
  width: 1560,
  height: 1020,
  groups: [
    { label: "エントリポイント", x: 40, y: 92, w: 1480, h: 96, stroke: "rgba(167,139,250,0.4)", fill: "rgba(167,139,250,0.05)" },
    { label: "エージェントサービス (Cloud Run)", x: 40, y: 220, w: 1480, h: 150, stroke: "rgba(52,168,83,0.4)", fill: "rgba(52,168,83,0.05)" },
    { label: "共有プラットフォーム", x: 40, y: 410, w: 1480, h: 150, stroke: "rgba(66,133,244,0.4)", fill: "rgba(66,133,244,0.05)" },
    { label: "共通 GCP データ / AI プレーン", x: 40, y: 600, w: 1480, h: 360, stroke: "rgba(251,188,4,0.4)", fill: "rgba(251,188,4,0.05)" },
  ],
  nodes: [
    // entrypoints
    { id: "line", label: "LINE Platform", sub: "Messaging API", icon: "x-line", x: 360, y: 116, cat: "external" },
    { id: "web", label: "Web Users", sub: "ブラウザ", icon: "gcp-users", x: 980, y: 116, cat: "external" },

    // agent services (Cloud Run)
    { id: "dlb", label: "driving-license-bot", sub: "学科試験 / Claude", icon: "gcp-cloud_run", x: 70, y: 262, w: 220, cat: "compute" },
    { id: "info", label: "fujisawa-info-bot", sub: "生活情報 / LangGraph", icon: "gcp-cloud_run", x: 320, y: 262, w: 220, cat: "compute" },
    { id: "piyo", label: "piyolog-analytics", sub: "育児ログ / Gemini", icon: "gcp-cloud_run", x: 570, y: 262, w: 220, cat: "compute" },
    { id: "kanie", label: "kanie-lab-agent", sub: "院試 Web / Claude", icon: "gcp-cloud_run", x: 980, y: 262, w: 240, cat: "compute" },

    // shared platforms
    { id: "fp", label: "fujisawa-platform", sub: "ETL Jobs · pgvector KB", icon: "gcp-cloud_run", x: 320, y: 452, w: 220, cat: "compute" },
    { id: "sp", label: "security-platform", sub: "MCP Proxy · DLP", icon: "gcp-cloud_run", x: 700, y: 452, w: 220, cat: "compute" },
    { id: "ap", label: "analytics-platform", sub: "uploader → BigQuery / dbt", icon: "gcp-cloud_run", x: 1080, y: 452, w: 240, cat: "compute" },

    // shared GCP data / AI plane
    { id: "vertex", label: "Vertex AI", sub: "Claude / Gemini / embedding", icon: "gcp-vertexai", x: 120, y: 660, cat: "ai" },
    { id: "firestore", label: "Firestore", sub: "sessions / users", icon: "gcp-firestore", x: 120, y: 770, cat: "data" },
    { id: "sql", label: "Cloud SQL", sub: "Postgres + pgvector", icon: "gcp-cloud_sql", x: 120, y: 880, cat: "data" },

    { id: "bq", label: "BigQuery", sub: "raw / staging / marts", icon: "x-bigquery", x: 460, y: 660, cat: "data" },
    { id: "gcs", label: "Cloud Storage", sub: "JSONL / PDF / backup", icon: "gcp-cloud_storage", x: 460, y: 770, cat: "data" },
    { id: "mcp", label: "MCP Tools", sub: "Google / arXiv / e-Stat …", icon: "x-python", x: 460, y: 880, cat: "external" },

    { id: "secret", label: "Secret Manager", sub: "鍵 / 資格情報", icon: "gcp-secret_manager", x: 800, y: 660, cat: "ops" },
    { id: "ar", label: "Artifact Registry", sub: "コンテナイメージ", icon: "gcp-artifact_registry", x: 800, y: 770, cat: "ops" },
    { id: "build", label: "Cloud Build", sub: "CI / deploy", icon: "gcp-cloud_build", x: 800, y: 880, cat: "ops" },

    { id: "wf", label: "Workflows + Scheduler", sub: "ETL / dbt 定期実行", icon: "gcp-cloud_build", x: 1140, y: 660, w: 220, cat: "ops" },
    { id: "obs", label: "Logging / Monitoring", sub: "ログ / アラート", icon: "gcp-cloud_logging", x: 1140, y: 770, w: 220, cat: "ops" },
    { id: "auth", label: "Firebase Auth", sub: "kanie-lab 認証", icon: "gcp-identity_and_access_management", x: 1140, y: 880, w: 220, cat: "ops" },
  ],
  edges: [
    // entry → services
    { from: "line", to: "dlb" },
    { from: "line", to: "info" },
    { from: "line", to: "piyo" },
    { from: "web", to: "kanie" },

    // services → shared platforms (integrations)
    { from: "info", to: "fp", label: "KB 参照" },
    { from: "dlb", to: "sp", label: "MCP", dashed: true },
    { from: "kanie", to: "sp", label: "MCP", dashed: true },
    { from: "dlb", to: "ap", label: "計装", dashed: true },
    { from: "piyo", to: "ap", label: "計装", dashed: true },

    // services → data/AI plane (representative)
    { from: "dlb", to: "vertex" },
    { from: "piyo", to: "vertex" },
    { from: "dlb", to: "firestore" },
    { from: "info", to: "firestore" },
    { from: "piyo", to: "sql" },
    { from: "kanie", to: "auth", dashed: true },

    // platforms → plane
    { from: "fp", to: "sql", label: "upsert" },
    { from: "fp", to: "gcs" },
    { from: "sp", to: "mcp" },
    { from: "ap", to: "gcs" },
    { from: "ap", to: "bq", label: "external → dbt" },
    { from: "ap", to: "wf", dashed: true },
  ],
};
