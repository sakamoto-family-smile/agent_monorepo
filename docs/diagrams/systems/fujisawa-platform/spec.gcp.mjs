// fujisawa-platform — GCP architecture spec.
// Shared base for crawl / PDF parse / vector search / ETL. No LINE entrypoint.
// Source: README + terraform (cloud_run_jobs ETL for_each, scheduler, cloudsql
// kb db, gcs pdf_archive, secrets, iam). ETL jobs: weekly_crawl,
// half_yearly_facility, biyearly_admission(1st/2nd), monthly_vacancy.
export const spec = {
  title: "fujisawa-platform — GCP",
  subtitle: "藤沢市 共有基盤 · ETL Cloud Run Jobs · pgvector KB",
  width: 1320,
  height: 680,
  groups: [
    { label: "project — asia-northeast1", x: 250, y: 150, w: 820, h: 470 },
    { label: "consumer agents (path dep)", x: 1090, y: 150, w: 200, h: 250, stroke: "rgba(167,139,250,0.4)", fill: "rgba(167,139,250,0.06)" },
  ],
  nodes: [
    { id: "city", label: "藤沢市 HP / PDF", sub: "一次ソース (crawl 対象)", icon: "x-globe", x: 540, y: 28, cat: "external" },

    { id: "sched", label: "Cloud Scheduler", sub: "weekly / monthly / 半期 cron", icon: "gcp-cloud_build", x: 300, y: 220, cat: "ops" },
    { id: "etl", label: "ETL Cloud Run Jobs", sub: "crawl · facility · admission · vacancy", icon: "gcp-cloud_run", x: 540, y: 220, w: 240, cat: "compute" },

    { id: "vertex", label: "Vertex AI", sub: "embedding (本番)", icon: "gcp-vertexai", x: 860, y: 220, cat: "ai" },
    { id: "docling", label: "docling", sub: "PDF 構造化 (Job 内)", icon: "x-python", x: 860, y: 320, cat: "local" },

    { id: "sql", label: "Cloud SQL", sub: "fujisawa_kb_db (pgvector)", icon: "gcp-cloud_sql", x: 440, y: 400, cat: "data" },
    { id: "gcs", label: "Cloud Storage", sub: "pdf_archive バケット", icon: "gcp-cloud_storage", x: 680, y: 400, cat: "data" },

    { id: "secret", label: "Secret Manager", sub: "DB / user-agent / vertex", icon: "gcp-secret_manager", x: 40, y: 300, w: 188, cat: "ops" },
    { id: "ar", label: "Artifact Registry", sub: "ETL イメージ", icon: "gcp-artifact_registry", x: 40, y: 400, w: 188, cat: "ops" },
    { id: "obs", label: "Cloud Logging", sub: "Job ログ", icon: "gcp-cloud_logging", x: 40, y: 500, w: 188, cat: "ops" },

    { id: "infobot", label: "info-bot", sub: "KB 参照", icon: "x-line", x: 1110, y: 220, w: 160, cat: "external" },
    { id: "hokatsu", label: "保活 agent", sub: "KB 参照", icon: "x-line", x: 1110, y: 300, w: 160, cat: "external" },
  ],
  edges: [
    { from: "sched", to: "etl", label: "run job" },
    { from: "city", to: "etl", label: "crawl" },
    { from: "etl", to: "vertex", label: "embed" },
    { from: "etl", to: "docling", dashed: true },
    { from: "etl", to: "sql", label: "upsert KB" },
    { from: "etl", to: "gcs", label: "PDF 保存" },
    { from: "etl", to: "secret", dashed: true },
    { from: "infobot", to: "sql", dashed: true },
    { from: "hokatsu", to: "sql", dashed: true },
  ],
};
