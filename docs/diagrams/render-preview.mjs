// Standalone renderer: produces a static SVG matching GcpArchitecture.tsx
// (now using the official Google Cloud icon sprite) so the diagram can be
// viewed without a React build.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ICON_DEFS = readFileSync(join(HERE, "gcp-icon-defs.partial.svg"), "utf8");

const TOKENS = {
  bg: "#0b1220", grid: "rgba(148,163,184,0.08)", edge: "#64748b",
  text: "#e2e8f0", textMuted: "#94a3b8",
  vpc: "rgba(66,133,244,0.06)", vpcStroke: "rgba(66,133,244,0.35)", radius: 14,
};
const CAT = {
  network: { fill: "#1f3a8a", stroke: "#4285F4" },
  compute: { fill: "#0f3d2e", stroke: "#34A853" },
  data: { fill: "#3b2a06", stroke: "#FBBC04" },
  ai: { fill: "#3a1620", stroke: "#EA4335" },
  ops: { fill: "#1f2937", stroke: "#94a3b8" },
};
const NW = 196, NH = 64;
const NODES = [
  { id: "users", label: "Users", sub: "Web / Mobile", icon: "users", x: 522, y: 24, cat: "ops" },
  { id: "lb", label: "Cloud Load Balancing", sub: "Global HTTPS LB", icon: "cloud_load_balancing", x: 522, y: 132, cat: "network" },
  { id: "fe", label: "Cloud Run — Frontend", sub: "Next.js 15", icon: "cloud_run", x: 300, y: 258, cat: "compute" },
  { id: "api", label: "Cloud Run — API", sub: "FastAPI / LLM", icon: "cloud_run", x: 744, y: 258, cat: "compute" },
  { id: "vertex", label: "Vertex AI", sub: "Gemini models", icon: "vertexai", x: 988, y: 258, cat: "ai" },
  { id: "pubsub", label: "Pub/Sub", sub: "Async jobs", icon: "pubsub", x: 744, y: 372, cat: "data" },
  { id: "fn", label: "Cloud Functions", sub: "Worker", icon: "cloud_functions", x: 988, y: 372, cat: "compute" },
  { id: "firestore", label: "Firestore", sub: "Sessions / chat", icon: "firestore", x: 300, y: 488, cat: "data" },
  { id: "sql", label: "Cloud SQL", sub: "PostgreSQL", icon: "cloud_sql", x: 522, y: 488, cat: "data" },
  { id: "gcs", label: "Cloud Storage", sub: "Artifacts / files", icon: "cloud_storage", x: 744, y: 488, cat: "data" },
  { id: "secret", label: "Secret Manager", sub: "Keys / tokens", icon: "secret_manager", x: 48, y: 258, w: 172, cat: "ops" },
  { id: "iam", label: "IAM", sub: "Identities / roles", icon: "identity_and_access_management", x: 48, y: 350, w: 172, cat: "ops" },
  { id: "obs", label: "Cloud Logging", sub: "Logs / Monitoring", icon: "cloud_logging", x: 48, y: 442, w: 172, cat: "ops" },
  { id: "build", label: "Cloud Build", sub: "CI pipeline", icon: "cloud_build", x: 300, y: 612, cat: "ops" },
  { id: "ar", label: "Artifact Registry", sub: "Container images", icon: "artifact_registry", x: 522, y: 612, cat: "ops" },
];
const EDGES = [
  { from: "users", to: "lb", label: "HTTPS" }, { from: "lb", to: "fe" }, { from: "lb", to: "api" },
  { from: "fe", to: "api", label: "REST / SSE" }, { from: "api", to: "vertex", label: "inference" },
  { from: "api", to: "firestore" }, { from: "api", to: "sql" }, { from: "api", to: "gcs" },
  { from: "api", to: "pubsub", label: "publish" }, { from: "pubsub", to: "fn" },
  { from: "fn", to: "gcs", dashed: true }, { from: "fn", to: "vertex", dashed: true },
  { from: "build", to: "ar" }, { from: "ar", to: "fe", label: "deploy", dashed: true },
  { from: "ar", to: "api", label: "deploy", dashed: true },
];
const M = new Map(NODES.map((n) => [n.id, n]));
const ctr = (n) => ({ cx: n.x + (n.w ?? NW) / 2, cy: n.y + (n.h ?? NH) / 2 });
function anchor(f, t) {
  const a = ctr(f), b = ctr(t);
  const ep = (c, hw, hh, tx, ty) => {
    const dx = tx - c.cx, dy = ty - c.cy;
    if (!dx && !dy) return { x: c.cx, y: c.cy };
    const s = 1 / Math.max(Math.abs(dx) / hw, Math.abs(dy) / hh);
    return { x: c.cx + dx * s, y: c.cy + dy * s };
  };
  return {
    p1: ep(a, (f.w ?? NW) / 2, (f.h ?? NH) / 2, b.cx, b.cy),
    p2: ep(b, (t.w ?? NW) / 2, (t.h ?? NH) / 2, a.cx, a.cy),
  };
}
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1240 712" width="1240" height="712" font-family="Inter, system-ui, sans-serif">
<defs>
<pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M 32 0 L 0 0 0 32" fill="none" stroke="${TOKENS.grid}" stroke-width="1"/></pattern>
<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="${TOKENS.edge}"/></marker>
${ICON_DEFS}
</defs>
<rect width="1240" height="712" fill="${TOKENS.bg}"/>
<rect width="1240" height="712" fill="url(#grid)"/>
<rect x="252" y="210" width="764" height="342" rx="20" fill="${TOKENS.vpc}" stroke="${TOKENS.vpcStroke}" stroke-width="1.5" stroke-dasharray="3 6"/>
<text x="272" y="236" fill="${TOKENS.vpcStroke}" font-size="12.5" font-weight="700" letter-spacing="1">VPC — asia-northeast1</text>`;
for (const e of EDGES) {
  const f = M.get(e.from), t = M.get(e.to); const { p1, p2 } = anchor(f, t);
  const mx = (p1.x + p2.x) / 2, my = (p1.y + p2.y) / 2;
  const d = `M ${p1.x} ${p1.y} Q ${mx} ${p1.y} ${mx} ${my} T ${p2.x} ${p2.y}`;
  s += `<path d="${d}" fill="none" stroke="${TOKENS.edge}" stroke-width="1.5"${e.dashed ? ' stroke-dasharray="6 6"' : ""} marker-end="url(#arrow)"/>`;
  if (e.label) s += `<text x="${mx}" y="${my - 6}" fill="${TOKENS.textMuted}" font-size="11" text-anchor="middle" paint-order="stroke" stroke="${TOKENS.bg}" stroke-width="4">${esc(e.label)}</text>`;
}
for (const n of NODES) {
  const c = CAT[n.cat], w = n.w ?? NW, h = n.h ?? NH, cy = (h - 34) / 2;
  s += `<g transform="translate(${n.x},${n.y})">
<rect width="${w}" height="${h}" rx="${TOKENS.radius}" fill="${c.fill}" stroke="${c.stroke}" stroke-width="1.25"/>
<rect width="5" height="${h}" rx="2.5" fill="${c.stroke}"/>
<rect x="14" y="${cy}" width="34" height="34" rx="9" fill="#f1f5f9"/>
<use href="#gcp-${n.icon}" x="17" y="${cy + 3}" width="28" height="28"/>
<text x="60" y="${h / 2 - 9}" fill="${TOKENS.text}" font-size="13" font-weight="650">${esc(n.label)}</text>
<text x="60" y="${h / 2 + 11}" fill="${TOKENS.textMuted}" font-size="11.5">${esc(n.sub)}</text>
</g>`;
}
s += `</svg>`;
writeFileSync(join(HERE, "gcp-architecture.svg"), s);
console.log("wrote gcp-architecture.svg");
