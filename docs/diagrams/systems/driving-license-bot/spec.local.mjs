// driving-license-bot — LOCAL / dev architecture spec.
// Source of truth: README "アーキテクチャの概要", docs/SETUP.md, app/config.py.
// Local mode runs a single FastAPI process with in-memory repositories; only
// the LLM calls reach the cloud (Vertex AI). External webhooks tunnel in via
// ngrok.
export const spec = {
  title: "driving-license-bot — Local / Dev",
  subtitle: "in-memory repos · uvicorn · ngrok tunnel · Vertex AI のみクラウド利用",
  width: 1180,
  height: 660,
  groups: [
    { label: "Developer machine — docker / uvicorn", x: 232, y: 234, w: 632, h: 392 },
  ],
  nodes: [
    { id: "line", label: "LINE Platform", sub: "Webhook 送信元", icon: "x-line", x: 470, y: 28, cat: "external" },
    { id: "ngrok", label: "ngrok", sub: "https → localhost:8080", icon: "x-ngrok", x: 470, y: 124, cat: "external" },

    { id: "app", label: "FastAPI app", sub: "uvicorn :8080 (line + agent)", icon: "x-fastapi", x: 470, y: 280, cat: "local" },
    { id: "mem", label: "In-memory repos", sub: "REPOSITORY_BACKEND=memory", icon: "x-python", x: 264, y: 400, cat: "local" },
    { id: "qbank", label: "Question bank", sub: "in-memory backend", icon: "x-python", x: 600, y: 400, cat: "local" },
    { id: "pg", label: "Postgres + pgvector", sub: "任意: docker / Cloud SQL proxy", icon: "x-postgres", x: 470, y: 520, cat: "local" },

    { id: "vertex", label: "Vertex AI", sub: "Claude / Gemini (asia-northeast1)", icon: "gcp-vertexai", x: 900, y: 280, cat: "ai" },
  ],
  edges: [
    { from: "line", to: "ngrok", label: "webhook" },
    { from: "ngrok", to: "app" },
    { from: "app", to: "mem" },
    { from: "app", to: "qbank" },
    { from: "qbank", to: "pg", label: "pgvector 時", dashed: true },
    { from: "app", to: "vertex", label: "LLM 生成/採点" },
  ],
};
