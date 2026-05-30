// piyolog-analytics — LOCAL / dev architecture spec.
// Source: app/config.py (DATABASE_URL 既定 sqlite+aiosqlite, legacy
// PIYOLOG_DB_PATH) + README (make backup/restore, ローカル相談は Vertex 任意).
export const spec = {
  title: "piyolog-analytics — Local / Dev",
  subtitle: "uvicorn · SQLite 既定 · 相談は Vertex 任意",
  width: 1140,
  height: 600,
  groups: [
    { label: "Developer machine — docker / uvicorn", x: 232, y: 224, w: 600, h: 340 },
  ],
  nodes: [
    { id: "line", label: "LINE Platform", sub: "Webhook 送信元", icon: "x-line", x: 460, y: 24, cat: "external" },
    { id: "ngrok", label: "ngrok", sub: "https → localhost", icon: "x-ngrok", x: 460, y: 120, cat: "external" },

    { id: "app", label: "FastAPI app", sub: "uvicorn (parser + analytics)", icon: "x-fastapi", x: 460, y: 270, cat: "local" },
    { id: "viz", label: "visualizer", sub: "グラフ画像生成", icon: "x-python", x: 270, y: 400, cat: "local" },
    { id: "sqlite", label: "SQLite", sub: "DATABASE_URL 既定 (aiosqlite)", icon: "x-postgres", x: 600, y: 400, cat: "local" },

    { id: "vertex", label: "Vertex AI", sub: "Gemini 相談 (任意)", icon: "gcp-vertexai", x: 880, y: 270, cat: "ai" },
  ],
  edges: [
    { from: "line", to: "ngrok", label: "webhook" },
    { from: "ngrok", to: "app" },
    { from: "app", to: "viz", label: "画像" },
    { from: "app", to: "sqlite", label: "冪等保存" },
    { from: "app", to: "vertex", label: "相談 (任意)", dashed: true },
  ],
};
