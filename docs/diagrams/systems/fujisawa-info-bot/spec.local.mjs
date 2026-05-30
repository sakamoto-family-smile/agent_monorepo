// fujisawa-info-bot — LOCAL / dev architecture spec.
// Source: README §3 dir layout + config.py factories
// (build_llm_client: mock|vertex_anthropic, build_knowledge_backend: inmemory|pgvector).
export const spec = {
  title: "fujisawa-info-bot — Local / Dev",
  subtitle: "uvicorn · in-memory KB · LLM は mock または Vertex",
  width: 1160,
  height: 620,
  groups: [
    { label: "Developer machine — docker / uvicorn", x: 232, y: 224, w: 600, h: 360 },
  ],
  nodes: [
    { id: "line", label: "LINE Platform", sub: "Webhook 送信元", icon: "x-line", x: 460, y: 24, cat: "external" },
    { id: "ngrok", label: "ngrok", sub: "https → localhost", icon: "x-ngrok", x: 460, y: 120, cat: "external" },

    { id: "app", label: "FastAPI app", sub: "uvicorn (api + graph)", icon: "x-fastapi", x: 460, y: 270, cat: "local" },
    { id: "graph", label: "LangGraph Supervisor", sub: "intent → RAG", icon: "x-python", x: 270, y: 400, cat: "local" },
    { id: "kb", label: "In-memory KB", sub: "build_knowledge_backend=inmemory", icon: "x-python", x: 600, y: 400, cat: "local" },

    { id: "llm", label: "LLM", sub: "mock / vertex_anthropic", icon: "gcp-vertexai", x: 880, y: 270, cat: "ai" },
  ],
  edges: [
    { from: "line", to: "ngrok", label: "webhook" },
    { from: "ngrok", to: "app" },
    { from: "app", to: "graph" },
    { from: "graph", to: "kb", label: "検索" },
    { from: "graph", to: "llm", label: "回答生成" },
  ],
};
