// analytics-platform — GCP architecture spec.
// Observability/ETL backbone. Agents emit events → uploader → GCS JSONL
// (raw/payloads/dead_letter) → BigQuery external table → dbt Cloud Run Job
// (raw/staging/marts), driven by Workflows + Scheduler, Monitoring alerts.
// Source: README §4 layout + workflows/dbt_pipeline.yaml + terraform
// (bigquery 3 datasets + external table, gcs 3 buckets, iam SAs, monitoring).
// Region: us-central1 (per workflow default).
export const spec = {
  title: "analytics-platform — GCP",
  subtitle: "計装イベント基盤 · GCS → BigQuery external → dbt · us-central1",
  width: 1340,
  height: 700,
  groups: [
    { label: "project — us-central1", x: 250, y: 150, w: 880, h: 480 },
    { label: "計装元エージェント", x: 40, y: 150, w: 188, h: 250, stroke: "rgba(167,139,250,0.4)", fill: "rgba(167,139,250,0.06)" },
  ],
  nodes: [
    { id: "agents", label: "Agents (計装)", sub: "stock / lifeplanner / piyolog …", icon: "x-python", x: 44, y: 200, w: 180, cat: "external" },

    { id: "uploader", label: "uploader", sub: "AnalyticsLogger → JSONL", icon: "x-python", x: 300, y: 200, cat: "local" },
    { id: "raw", label: "GCS — raw", sub: "uploaded/ JSONL", icon: "gcp-cloud_storage", x: 300, y: 320, cat: "data" },
    { id: "payloads", label: "GCS — payloads", sub: "大容量 payload", icon: "gcp-cloud_storage", x: 300, y: 420, cat: "data" },
    { id: "dlq", label: "GCS — dead_letter", sub: "失敗イベント", icon: "gcp-cloud_storage", x: 300, y: 520, cat: "data" },

    { id: "ext", label: "BigQuery external", sub: "agent_events_external", icon: "x-bigquery", x: 580, y: 320, cat: "data" },
    { id: "dbt", label: "dbt Cloud Run Job", sub: "run + test", icon: "gcp-cloud_run", x: 580, y: 200, cat: "compute" },
    { id: "marts", label: "BigQuery datasets", sub: "raw / staging / marts", icon: "x-bigquery", x: 840, y: 320, cat: "data" },

    { id: "wf", label: "Workflows", sub: "dbt_pipeline", icon: "gcp-cloud_build", x: 840, y: 200, cat: "ops" },
    { id: "sched", label: "Cloud Scheduler", sub: "定期トリガー", icon: "gcp-cloud_build", x: 840, y: 480, cat: "ops" },
    { id: "mon", label: "Cloud Monitoring", sub: "job failed / slow アラート", icon: "gcp-cloud_logging", x: 580, y: 480, cat: "ops" },

    { id: "ar", label: "Artifact Registry", sub: "dbt イメージ", icon: "gcp-artifact_registry", x: 1150, y: 200, w: 170, cat: "ops" },
  ],
  edges: [
    { from: "agents", to: "uploader", label: "emit" },
    { from: "uploader", to: "raw" },
    { from: "uploader", to: "payloads", dashed: true },
    { from: "uploader", to: "dlq", label: "fail", dashed: true },
    { from: "raw", to: "ext", label: "external read" },
    { from: "ext", to: "dbt", dashed: true },
    { from: "dbt", to: "marts", label: "build" },
    { from: "wf", to: "dbt", label: "run job" },
    { from: "sched", to: "wf", label: "cron" },
    { from: "dbt", to: "mon", dashed: true },
  ],
};
