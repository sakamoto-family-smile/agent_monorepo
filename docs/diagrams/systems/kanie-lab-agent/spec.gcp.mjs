// kanie-lab-agent — GCP architecture spec.
// 大学院入試準備 Web エージェント。Next.js frontend + FastAPI backend
// (Claude Agent SDK) を Cloud Run に配備。Firebase Auth + Firestore。
// MCP ツールは security-platform proxy 経由。
// Source: README (技術スタック) + infra/cloudrun/{frontend,backend}.yaml +
// infra/scripts/setup-gcp.sh (firestore, secrets, artifacts, SAs) + docker-compose.
export const spec = {
  title: "kanie-lab-agent — GCP",
  subtitle: "院試準備 Web エージェント · Cloud Run · Firebase · Claude",
  width: 1340,
  height: 680,
  groups: [
    { label: "project — asia-northeast1", x: 250, y: 150, w: 840, h: 470 },
  ],
  nodes: [
    { id: "users", label: "Users", sub: "Web ブラウザ", icon: "gcp-users", x: 540, y: 24, cat: "external" },

    { id: "fe", label: "kanie-lab-frontend", sub: "Cloud Run · Next.js 15 / React 19", icon: "gcp-cloud_run", x: 540, y: 150, w: 240, cat: "compute" },
    { id: "be", label: "kanie-lab-backend", sub: "Cloud Run · FastAPI / Claude Agent SDK", icon: "gcp-cloud_run", x: 540, y: 280, w: 260, cat: "compute" },

    { id: "auth", label: "Firebase Auth", sub: "認証", icon: "gcp-identity_and_access_management", x: 300, y: 220, cat: "ops" },
    { id: "firestore", label: "Firestore", sub: "セッション / 研究計画", icon: "gcp-firestore", x: 300, y: 400, cat: "data" },

    { id: "claude", label: "Anthropic Claude", sub: "claude-sonnet-4-6", icon: "x-globe", x: 880, y: 280, cat: "ai" },

    { id: "proxy", label: "MCP Proxy", sub: "security-platform 経由", icon: "gcp-cloud_run", x: 560, y: 410, cat: "compute" },
    { id: "mcp", label: "MCP Tools", sub: "Google/Brave/arXiv/e-Stat …", icon: "x-python", x: 820, y: 410, cat: "external" },

    { id: "secret", label: "Secret Manager", sub: "ANTHROPIC_API_KEY / Firebase", icon: "gcp-secret_manager", x: 40, y: 300, w: 188, cat: "ops" },
    { id: "ar", label: "Artifact Registry", sub: "frontend / backend image", icon: "gcp-artifact_registry", x: 40, y: 400, w: 188, cat: "ops" },
    { id: "build", label: "Cloud Build", sub: "CI / deploy", icon: "gcp-cloud_build", x: 40, y: 500, w: 188, cat: "ops" },
  ],
  edges: [
    { from: "users", to: "fe", label: "HTTPS" },
    { from: "fe", to: "auth", label: "認証", dashed: true },
    { from: "fe", to: "be", label: "BACKEND_URL" },
    { from: "be", to: "claude", label: "agent" },
    { from: "be", to: "firestore" },
    { from: "be", to: "proxy", label: "tool call" },
    { from: "proxy", to: "mcp" },
    { from: "be", to: "secret", dashed: true },
    { from: "build", to: "ar", dashed: true },
  ],
};
