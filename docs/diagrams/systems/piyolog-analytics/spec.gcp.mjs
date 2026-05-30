// piyolog-analytics — GCP architecture spec.
// 育児ログ(.txt) を解析する LINE Bot。Cloud Run は cloudbuild 経由で配備
// (terraform は Cloud SQL / GCS backup / IAM / secrets を管理)。
// Source: README (機能) + terraform (cloud_sql, backup_bucket, secrets, iam,
// artifact_registry) + app/services (analytics, consultation, visualizer).
export const spec = {
  title: "piyolog-analytics — GCP",
  subtitle: "育児ログ LINE Bot · Cloud Run · Cloud SQL · Vertex Gemini",
  width: 1300,
  height: 660,
  groups: [
    { label: "project — asia-northeast1", x: 250, y: 150, w: 800, h: 400 },
  ],
  nodes: [
    { id: "line", label: "LINE Platform", sub: ".txt 添付 / コマンド", icon: "x-line", x: 540, y: 24, cat: "external" },
    { id: "run", label: "piyolog service", sub: "Cloud Run · FastAPI", icon: "gcp-cloud_run", x: 540, y: 160, w: 240, cat: "compute" },

    { id: "vertex", label: "Vertex AI", sub: "Gemini 相談 / NL 照会", icon: "gcp-vertexai", x: 880, y: 160, cat: "ai" },

    { id: "parser", label: "parser / analytics", sub: "冪等保存 + 集計", icon: "x-python", x: 300, y: 300, cat: "local" },
    { id: "viz", label: "visualizer", sub: "グラフ画像生成", icon: "x-python", x: 540, y: 300, cat: "local" },

    { id: "sql", label: "Cloud SQL", sub: "Postgres (events / children)", icon: "gcp-cloud_sql", x: 540, y: 420, cat: "data" },
    { id: "gcs", label: "Cloud Storage", sub: "backup / restore", icon: "gcp-cloud_storage", x: 800, y: 420, cat: "data" },

    { id: "secret", label: "Secret Manager", sub: "LINE鍵 / DATABASE_URL", icon: "gcp-secret_manager", x: 40, y: 300, w: 188, cat: "ops" },
    { id: "ar", label: "Artifact Registry", sub: "コンテナイメージ", icon: "gcp-artifact_registry", x: 40, y: 400, w: 188, cat: "ops" },
    { id: "build", label: "Cloud Build", sub: "CI / deploy", icon: "gcp-cloud_build", x: 40, y: 500, w: 188, cat: "ops" },
  ],
  edges: [
    { from: "line", to: "run", label: "webhook" },
    { from: "run", to: "parser" },
    { from: "run", to: "viz", label: "画像" },
    { from: "run", to: "vertex", label: "相談" },
    { from: "parser", to: "sql" },
    { from: "sql", to: "gcs", label: "export", dashed: true },
    { from: "run", to: "secret", dashed: true },
    { from: "build", to: "ar", dashed: true },
  ],
};
