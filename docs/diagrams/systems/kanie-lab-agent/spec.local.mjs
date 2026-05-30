// kanie-lab-agent — LOCAL / dev architecture spec.
// Source: docker-compose.yml (frontend, backend, firebase-emulator,
// mcp-google-search, security-proxy) + README local setup (Docker Desktop).
export const spec = {
  title: "kanie-lab-agent — Local / Dev",
  subtitle: "docker-compose · Firebase Emulator · MCP + security-proxy",
  width: 1200,
  height: 600,
  groups: [
    { label: "Developer machine — docker-compose", x: 232, y: 130, w: 760, h: 400 },
  ],
  nodes: [
    { id: "browser", label: "Browser", sub: "localhost:3000", icon: "gcp-users", x: 60, y: 250, cat: "external" },

    { id: "fe", label: "frontend", sub: "Next.js dev :3000", icon: "x-fastapi", x: 300, y: 190, cat: "local" },
    { id: "be", label: "backend", sub: "FastAPI :8000 / Claude Agent", icon: "x-python", x: 300, y: 320, cat: "local" },
    { id: "emu", label: "Firebase Emulator", sub: "auth :9099 / UI :4000", icon: "x-python", x: 560, y: 190, cat: "local" },

    { id: "proxy", label: "security-proxy", sub: "MCP gateway :8080", icon: "x-python", x: 560, y: 320, cat: "local" },
    { id: "mcp", label: "mcp-google-search", sub: "HTTP MCP :3001", icon: "x-python", x: 790, y: 320, cat: "local" },

    { id: "claude", label: "Anthropic Claude", sub: "ANTHROPIC_API_KEY", icon: "x-globe", x: 1010, y: 320, cat: "ai" },
  ],
  edges: [
    { from: "browser", to: "fe", label: "HTTP" },
    { from: "fe", to: "emu", label: "auth", dashed: true },
    { from: "fe", to: "be" },
    { from: "be", to: "claude", label: "agent" },
    { from: "be", to: "proxy", label: "tool" },
    { from: "proxy", to: "mcp" },
  ],
};
