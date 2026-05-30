// analytics-platform — LOCAL / dev architecture spec.
// Source: README §4 (docker-compose Phoenix, dbt profiles local=DuckDB) +
// gcp_config.py (ANALYTICS_STORAGE_BACKEND=local 既定 → local_uploader).
export const spec = {
  title: "analytics-platform — Local / Dev",
  subtitle: "local uploader · DuckDB (dbt) · Phoenix トレース",
  width: 1160,
  height: 520,
  groups: [
    { label: "Developer machine — docker-compose", x: 232, y: 120, w: 700, h: 360 },
  ],
  nodes: [
    { id: "agents", label: "Agents (計装)", sub: "demo_emit / run_etl", icon: "x-python", x: 270, y: 180, cat: "external" },
    { id: "uploader", label: "local_uploader", sub: "STORAGE_BACKEND=local", icon: "x-python", x: 270, y: 300, cat: "local" },
    { id: "files", label: "ローカル JSONL", sub: "ファイル出力", icon: "x-python", x: 510, y: 300, cat: "local" },

    { id: "dbt", label: "dbt", sub: "profiles: local = DuckDB", icon: "x-python", x: 510, y: 180, cat: "local" },
    { id: "duck", label: "DuckDB", sub: "raw / staging / marts", icon: "x-bigquery", x: 750, y: 180, cat: "data" },

    { id: "phoenix", label: "Phoenix", sub: "OTel トレース UI", icon: "x-globe", x: 750, y: 300, cat: "local" },
  ],
  edges: [
    { from: "agents", to: "uploader", label: "emit" },
    { from: "uploader", to: "files" },
    { from: "files", to: "dbt", label: "read", dashed: true },
    { from: "dbt", to: "duck", label: "build" },
    { from: "agents", to: "phoenix", label: "trace", dashed: true },
  ],
};
